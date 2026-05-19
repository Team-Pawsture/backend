"""
영상 분석 관련 API 라우터
- POST /analyses : 영상 분석 요청 (multipart/form-data)
- GET /analyses/{analysis_id} : 분석 결과 조회 (폴링)

2026-05-17 v2: 명세서 v2 기준 신규 구현
2026-05-17 v3: BackgroundTasks 비동기 흐름 적용
- AI /analyze가 평균 34초/최대 72초 동기 호출이라 요청 처리 중 응답 보류 불가
- 흐름:
  1) POST /analyses → 영상 저장 → Analysis(status=queued) 즉시 생성 → BackgroundTask 등록
  2) 라우터는 곧바로 queued 응답 반환 (프론트는 명세대로 2~3초 간격 폴링)
  3) 백그라운드 함수가 새 SessionLocal로 submit_analysis() 호출 → DB 업데이트
  4) GET /analyses/{id}는 DB 캐시만 읽음 (AI 서버 폴링 안 함)

────────────────────────────────────────────────────────────────────────────
⚠ BackgroundTasks 한계 (app/utils/ai_client.py docstring과 함께 참고)
────────────────────────────────────────────────────────────────────────────
- FastAPI BackgroundTasks는 응답 직후 같은 워커 프로세스에서 실행됨.
  · 워커 재시작/크래시 시 진행 중인 분석은 영구 queued로 잔존
  · uvicorn --workers N 사용 시 어느 워커에서 실행됐는지 추적 불가
  · 동시 분석은 워커 이벤트 루프 안에서 처리 (I/O 대기는 OK, 무제한 누적은 위험)
- 1차 배포 수준 수용. 전환 트리거:
  · 동시 진행 분석 5건 이상 정기 발생
  · 워커 재시작 시 잔존 queued 빈번
  · 멀티 워커/멀티 인스턴스 배포 필요
  → Celery/RQ + Redis로 마이그레이션
- 임시 보완: 1시간 이상 queued인 Analysis는 별도 배치로 failed 변환 권장.
"""

from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.user import User
from app.models.pet import Pet
from app.models.analysis import Analysis
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user
from app.utils.video_handler import (
    is_allowed_video_extension,
    save_analysis_video,
    delete_analysis_video,
)
from app.utils.ai_client import submit_analysis, fetch_keypoints, AIServerUnavailable
from app.utils.datetime_helper import to_kst_iso
from app.utils.url_helper import build_absolute_url


router = APIRouter(prefix="/analyses", tags=["영상 분석"])


# ============================================
# 공통 헬퍼
# ============================================
def _pet_or_raise(db: Session, pet_id: int, user_id: int) -> Pet:
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "PET404",
                "message": "해당 반려견을 찾을 수 없습니다.",
                "result": None,
            },
        )
    if pet.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "PET403",
                "message": "접근 권한이 없습니다.",
                "result": None,
            },
        )
    return pet


# ============================================
# POST /analyses — 영상 분석 요청 (multipart/form-data)
# ============================================
@router.post("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def create_analysis(
    background_tasks: BackgroundTasks,
    pet_id: int = Form(..., description="분석 대상 반려견 ID"),
    video: UploadFile = File(..., description="영상 파일 (mp4/mov/avi, 100MB 이하)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    분석 요청 생성
    - 권한 체크: 본인 반려견만 가능 (PET404/PET403)
    - 중복 방지: 동일 pet_id에 queued/running 상태 있으면 ANALYSIS409
    - 파일 검증: 확장자(mp4/mov/avi), 크기(100MB) — 검증 실패 시 COMMON400
    - 영상 저장 후 Analysis(status=queued) 생성 → 즉시 응답
    - AI 호출은 BackgroundTask에서 비동기 처리 (라우터 응답 후 실행)
    """
    pet = _pet_or_raise(db, pet_id, current_user.user_id)

    # 1. 중복 요청 차단 (queued/running)
    in_progress = (
        db.query(Analysis)
        .filter(Analysis.pet_id == pet.pet_id, Analysis.status.in_(["queued", "running"]))
        .first()
    )
    if in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS409",
                "message": "이미 진행 중인 분석이 있습니다. 완료된 후 다시 시도해주세요.",
                "result": None,
            },
        )

    # 2. 파일 첨부 + 확장자 검증
    if not video.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"video": "video 파일은 필수입니다"},
            },
        )

    if not is_allowed_video_extension(video.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "지원하지 않는 파일 형식입니다. (mp4, mov, avi 만 가능)",
                "result": None,
            },
        )

    # 3. 영상 저장 (크기 검증 포함)
    try:
        saved = await save_analysis_video(pet.pet_id, video)
    except ValueError as e:
        msg = "파일 크기는 100MB 이하여야 합니다." if "100MB" in str(e) else str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": msg,
                "result": None,
            },
        )

    # 4. Analysis 레코드 즉시 생성 (status=queued, job_id 없음)
    #    동시 요청 race 차단은 DB partial unique index(uq_analyses_pet_in_progress)에 위임.
    #    SELECT 기반 in_progress 체크(위 1번)는 일반 케이스 빠른 응답용이고,
    #    SELECT-INSERT 사이 동시 요청은 IntegrityError로 잡힘.
    #
    #    [Known limitation - mock 환경 테스트의 한계]
    #    Mock 모드(_mock_submit)는 100ms 이내 완료되므로 병렬 POST 두 건이
    #    각자 라우터에 도착하는 시점에 첫 BG가 이미 끝나 있을 가능성이 높음
    #    → partial index가 발동할 race window를 안정적으로 재현하기 어려움.
    #    실제 AI 서버(34초+)에선 첫 분석이 진행 중인 동안 두 번째 요청이 들어와
    #    SELECT 1차 체크 또는 INSERT의 partial index에서 차단됨.
    #    (DB 레벨 차단 효과는 psql로 동일 pet에 queued 행 2건 INSERT 시도로 확인 완료)
    new_analysis = Analysis(
        pet_id=pet.pet_id,
        video_url=saved["url_path"],
        job_id=None,
        status="queued",
    )
    db.add(new_analysis)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # partial unique index 충돌 = 동일 pet 진행 중 분석 존재 = 명세서 409 ANALYSIS409
        # 업로드된 영상은 사용 안 되므로 정리.
        delete_analysis_video(saved["file_path"])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS409",
                "message": "이미 진행 중인 분석이 있습니다. 완료된 후 다시 시도해주세요.",
                "result": None,
            },
        )
    db.refresh(new_analysis)

    # 5. 백그라운드 태스크 등록 — 응답 직후 실행됨
    #   주의: 라우터 의존성으로 받은 db 세션은 응답 후 닫히므로 백그라운드에서 사용 불가.
    #         _run_analysis_in_background()가 새 SessionLocal()을 직접 연다.
    background_tasks.add_task(
        _run_analysis_in_background,
        analysis_id=new_analysis.analysis_id,
        video_file_path=saved["file_path"],
    )

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="AI 분석 요청이 생성되었습니다.",
        result={
            "analysis_id": new_analysis.analysis_id,
            "pet_id": new_analysis.pet_id,
            "status": new_analysis.status,
            "created_at": to_kst_iso(new_analysis.created_at),
        },
    )


# ============================================
# GET /analyses/recent — 내 반려견의 최근 completed 분석 목록
# - /{analysis_id} 보다 먼저 등록되어야 path 매칭됨
# - 본인 반려견의 completed 상태만, 최신순 정렬
# ============================================
@router.get("/recent", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_recent_analyses(
    limit: int = Query(5, ge=1, le=20, description="조회 개수 (1~20, 기본 5)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    최근 분석 이력
    - 권한: JWT 토큰에서 user_id 추출, Pet.user_id 와 매칭되는 분석만
    - 필터: status=completed (queued/running/rejected/failed 제외)
    - 정렬: Analysis.created_at DESC
    - 응답 result: 배열. 분석 이력 없으면 빈 배열 []
    - pet_profile_image_url 은 GET /pets 와 동일하게 BASE_URL 포함 절대 URL
    """
    rows = (
        db.query(Analysis, Pet)
        .join(Pet, Analysis.pet_id == Pet.pet_id)
        .filter(
            Pet.user_id == current_user.user_id,
            Analysis.status == "completed",
        )
        .order_by(Analysis.created_at.desc())
        .limit(limit)
        .all()
    )

    items = [
        {
            "analysis_id": analysis.analysis_id,
            "pet_id": analysis.pet_id,
            "pet_name": pet.name,
            "pet_profile_image_url": build_absolute_url(pet.profile_image_url),
            "status": analysis.status,
            "risk_level": analysis.risk_level,
            "created_at": to_kst_iso(analysis.created_at),
            "completed_at": to_kst_iso(analysis.completed_at),
        }
        for analysis, pet in rows
    ]

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result=items,
    )


# ============================================
# GET /analyses/{analysis_id}/keypoints — 관절 좌표 시계열 (P7, 2026-05-19)
# - /{analysis_id} 보다 먼저 등록되어야 path 매칭됨
# - 프록시 성격: AI 응답을 result에 그대로 담아 반환 (변환 최소화)
# - completed 분석에서만 호출 가능 (queued/running/rejected/failed → 400 ANALYSIS400)
# ============================================
@router.get("/{analysis_id}/keypoints", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def get_analysis_keypoints(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    AI 프레임별 관절 키포인트 시계열 조회.
    - 권한: 본인 반려견의 분석만
    - 상태: completed 아니면 400 ANALYSIS400
    - AI 호출 실패: 503 ANALYSIS503 (기존 패턴 재사용)
    """
    analysis = db.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS404",
                "message": "해당 분석을 찾을 수 없습니다.",
                "result": None,
            },
        )

    pet = db.query(Pet).filter(Pet.pet_id == analysis.pet_id).first()
    if not pet or pet.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS403",
                "message": "접근 권한이 없습니다.",
                "result": None,
            },
        )

    if analysis.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS400",
                "message": "완료된 분석에서만 관절 좌표를 조회할 수 있습니다.",
                "result": None,
            },
        )

    # job_id 없으면 키포인트 조회 불가 (정상 흐름에선 completed면 job_id 존재)
    if not analysis.job_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS503",
                "message": "분석 job_id가 없어 키포인트를 조회할 수 없습니다.",
                "result": None,
            },
        )

    try:
        keypoints = await fetch_keypoints(analysis.job_id)
    except AIServerUnavailable as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS503",
                "message": f"AI 키포인트 서버를 사용할 수 없습니다. ({e})",
                "result": None,
            },
        )

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result=keypoints,
    )


# ============================================
# GET /analyses/{analysis_id} — 분석 상태 / 결과 조회 (폴링)
# ============================================
@router.get("/{analysis_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    분석 결과 조회 (프론트가 2~3초 간격으로 폴링)
    - 권한 체크: 본인 반려견의 분석만 조회 가능 (ANALYSIS403)
    - DB 캐시만 읽음. AI 서버 폴링은 BackgroundTask가 담당하므로 여기선 불필요.
    - 응답 필드 구성은 status에 따라 분기 (_build_analysis_response 참조)
    """
    analysis = db.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS404",
                "message": "해당 분석을 찾을 수 없습니다.",
                "result": None,
            },
        )

    pet = db.query(Pet).filter(Pet.pet_id == analysis.pet_id).first()
    if not pet or pet.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS403",
                "message": "접근 권한이 없습니다.",
                "result": None,
            },
        )

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result=_build_analysis_response(analysis),
    )


# ============================================
# 백그라운드 러너: AI 서버 호출 → DB 업데이트 → 영상 정리
# - 새 SessionLocal() 사용 (라우터 의존성 세션은 응답 후 닫힘)
# - try/finally로 세션과 영상 파일 모두 정리
# - AIServerUnavailable + 일반 Exception 모두 잡아 failed로 기록 (분실 방지)
# - 영상 파일은 분석 종료 시점에 삭제 — AI 서버가 자체 사본 보유, 프론트는 재폴링 안 함
# ============================================
async def _run_analysis_in_background(
    analysis_id: int,
    video_file_path: str,
) -> None:
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()
        if not analysis:
            # 이론상 발생 X (방금 생성한 레코드). 안전망.
            return

        try:
            ai_result = await submit_analysis(video_file_path)
        except AIServerUnavailable as e:
            # 환경변수 미설정/네트워크/5xx/4xx — DB에 실패 기록
            analysis.status = "failed"
            analysis.ai_result = {
                "prediction": None,
                "recommendation": None,
                "quality": None,
                "progress": None,
                "error_message": f"AI 서버 호출 실패: {e}",
            }
            analysis.completed_at = datetime.now(timezone.utc)
            db.commit()
            return
        except Exception as e:
            # 예상치 못한 예외도 분실 없이 failed로 기록 (분석 영구 queued 방지)
            analysis.status = "failed"
            analysis.ai_result = {
                "prediction": None,
                "recommendation": None,
                "quality": None,
                "progress": None,
                "error_message": f"AI 처리 중 예외: {type(e).__name__}: {e}",
            }
            analysis.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # 정상 결과 반영 (기존 _apply_poll_result 재사용)
        _apply_poll_result(db, analysis, ai_result)
    finally:
        db.close()
        # 영상 파일 정리: AI 서버가 자체 사본 보유. 백엔드 측 재폴링/재시도 없음.
        # 분석 종료 시점(성공/실패/거절) 모두 삭제. 디스크 누적 방지.
        delete_analysis_video(video_file_path)


# ============================================
# 내부 헬퍼: AI 결과(또는 폴링 결과)를 Analysis 레코드에 반영
# - ai_client._transform_ai_to_backend() 의 출력 구조를 그대로 받음
# - _internal_predicted_stage 가 있으면 ai_result 안에 그대로 보존
#   (병원 추천 점수 계산 시 hospitals.py 에서 참조)
# ============================================
def _apply_poll_result(db: Session, analysis: Analysis, poll: dict) -> None:
    new_status = poll.get("status")
    if new_status in ("queued", "running", "completed", "rejected", "failed"):
        analysis.status = new_status

    # job_id가 새로 들어왔으면 저장
    job_id = poll.get("job_id")
    if job_id and not analysis.job_id:
        analysis.job_id = job_id

    # ai_result에 전체 저장 (prediction / recommendation / quality / progress / error_message)
    # _internal_predicted_stage(있으면)는 응답에 노출되지 않지만 hospitals.py에서 참조하기 위해 보존.
    ai_result_payload = {
        "prediction": poll.get("prediction"),
        "recommendation": poll.get("recommendation"),
        "quality": poll.get("quality"),
        "progress": poll.get("progress"),
        "error_message": poll.get("error_message"),
    }
    if "_internal_predicted_stage" in poll:
        ai_result_payload["_internal_predicted_stage"] = poll["_internal_predicted_stage"]
    analysis.ai_result = ai_result_payload

    # risk_level 별도 컬럼에도 저장 (pets 상세 조회 시 join 비용 감소)
    risk = poll.get("risk_level")
    if not risk and isinstance(poll.get("prediction"), dict):
        risk = poll["prediction"].get("risk_level")
    if risk:
        analysis.risk_level = risk

    if analysis.status in ("completed", "rejected", "failed") and analysis.completed_at is None:
        analysis.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(analysis)


# ============================================
# 내부 헬퍼: Analysis → 명세서 형식 응답 dict
# - _internal_predicted_stage 는 응답에 노출하지 않음 (의료 정보 안전 정책)
# ============================================
def _build_analysis_response(analysis: Analysis) -> dict:
    ai = analysis.ai_result if isinstance(analysis.ai_result, dict) else {}
    base = {
        "analysis_id": analysis.analysis_id,
        "pet_id": analysis.pet_id,
        "status": analysis.status,
        "created_at": to_kst_iso(analysis.created_at),
        "completed_at": to_kst_iso(analysis.completed_at),
    }

    if analysis.status == "queued":
        base.update({"prediction": None, "recommendation": None, "quality": None})
        return base

    if analysis.status == "running":
        base.update(
            {
                "progress": ai.get("progress"),
                "prediction": None,
                "recommendation": None,
                "quality": None,
            }
        )
        return base

    if analysis.status == "completed":
        base.update(
            {
                "quality": ai.get("quality"),
                "prediction": ai.get("prediction"),
                "recommendation": ai.get("recommendation"),
            }
        )
        return base

    if analysis.status == "rejected":
        base.update(
            {
                "quality": ai.get("quality"),
                "prediction": None,
                "recommendation": ai.get("recommendation"),
            }
        )
        return base

    if analysis.status == "failed":
        base.update(
            {
                "error_message": ai.get("error_message") or "AI 분석 중 오류가 발생했습니다.",
                "prediction": None,
                "recommendation": None,
                "quality": None,
            }
        )
        return base

    return base

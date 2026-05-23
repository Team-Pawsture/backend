"""
영상 분석 관련 API 라우터
- POST /analyses : 영상 분석 요청 (JSON {pet_id, video_id})
- GET /analyses/{analysis_id} : 분석 결과 조회 (폴링)

2026-05-17 v2: 명세서 v2 기준 신규 구현
2026-05-22 v4: AI 서버 비동기 큐잉 전환
- AI POST /api/v1/patella/analyses 가 즉시 queued 응답 → job_id 발급.
- 흐름:
  1) POST /analyses → Analysis(status=queued, ai_job_id=None) 생성 + commit (analysis_id 확정)
  2) submit_analysis() 동기 호출 → ai_job_id 수신 (수초 내) → Analysis.ai_job_id 업데이트
  3) AI 호출 실패 시 status=failed 로 기록 후 503 반환
  4) GET /analyses/{id} 마다 status terminal 아니면 fetch_ai_job_status() 로 폴링
     · completed/rejected/failed → DB 영구 캐시
     · 폴링 실패(timeout 등) → 현재 DB 상태 그대로 응답 (클라가 재시도)
"""

from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.models.analysis import Analysis
from app.models.video import Video
from app.schemas.user import CommonResponse
from app.schemas.video import AnalysisCreateRequest
from app.utils.security import get_current_user
from app.utils.ai_client import (
    AIServerUnavailable,
    _transform_ai_to_backend,
    fetch_ai_job_status,
    fetch_keypoints,
    submit_analysis,
)
from app.utils.datetime_helper import to_kst_iso
# 2026-05-22 URL 정책 반전: 응답은 상대경로. AI 호출 시 절대 URL 변환은 ai_client 내부 처리.

TERMINAL_STATUSES = ("completed", "rejected", "failed")


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
# POST /analyses — 영상 분석 요청 (JSON 입력, 비동기 큐잉)
# - 영상 업로드는 사전에 POST /videos 로 분리됨
# - AI 서버는 즉시 queued 응답 → 백엔드는 ai_job_id 만 받아 저장
# ============================================
@router.post("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def create_analysis(
    payload: AnalysisCreateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    분석 요청 생성 (2026-05-22 v4, 비동기 큐잉)
    - 입력: JSON {pet_id, video_id}
    - 권한 체크: 본인 반려견만 가능 (PET404/PET403)
    - video_id 검증: 존재 + 소유자 일치 + pet_id 일치
    - 중복 방지: 동일 pet_id 에 queued/running 상태 있으면 ANALYSIS409
    - Analysis(status=queued, ai_job_id=None) 즉시 생성 → AI 큐잉 호출 → ai_job_id 저장
    - 영상 파일은 videos 테이블 소유. 분석 종료 후에도 삭제 X (영구 보존).
    """
    pet = _pet_or_raise(db, payload.pet_id, current_user.user_id)

    # 1. video_id 검증
    video = db.query(Video).filter(Video.video_id == payload.video_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "VIDEO404",
                "message": "해당 영상을 찾을 수 없습니다.",
                "result": None,
            },
        )
    if video.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "VIDEO403",
                "message": "해당 영상에 접근 권한이 없습니다.",
                "result": None,
            },
        )
    if video.pet_id != pet.pet_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"video_id": "video_id 가 pet_id 와 일치하지 않습니다"},
            },
        )

    # 2. 중복 요청 차단 (queued/running)
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

    # 3. Analysis 레코드 즉시 생성 (status=queued, ai_job_id 미정)
    new_analysis = Analysis(
        pet_id=pet.pet_id,
        video_id=video.video_id,
        video_url=video.file_url,
        job_id=None,
        ai_job_id=None,
        status="queued",
    )
    db.add(new_analysis)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
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

    # 4. AI 서버에 분석 요청 (즉시 ai_job_id 수신, 본 분석은 AI 큐에서 비동기 수행)
    try:
        submit_result = await submit_analysis(
            pet_id=pet.pet_id,
            video_id=video.video_id,
            video_url=video.file_url,
        )
    except AIServerUnavailable as e:
        new_analysis.status = "failed"
        new_analysis.ai_result = {
            "prediction": None,
            "recommendation": None,
            "quality": None,
            "progress": None,
            "error_message": f"AI 서버 호출 실패: {e}",
        }
        new_analysis.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS503",
                "message": f"AI 서버를 사용할 수 없습니다. ({e})",
                "result": None,
            },
        )

    # 5. ai_job_id + raw envelope 저장
    new_analysis.ai_job_id = submit_result["ai_job_id"]
    new_analysis.ai_result = submit_result.get("raw")
    db.commit()
    db.refresh(new_analysis)

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
            "pet_profile_image_url": pet.profile_image_url,
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
    - 흐름:
      1) 분석 + 권한 검증
      2) status 가 terminal(completed/rejected/failed) 이면 DB 캐시로 즉시 응답
      3) terminal 아니고 ai_job_id 있으면 fetch_ai_job_status() 호출
         · 성공 시 DB 업데이트 후 응답
         · 실패(timeout 등) 시 현재 DB 상태 그대로 응답 (클라가 재시도)
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

    # terminal 아니고 ai_job_id 있으면 AI 폴링 시도
    if analysis.status not in TERMINAL_STATUSES and analysis.ai_job_id:
        try:
            raw_envelope = await fetch_ai_job_status(analysis.ai_job_id)
            _apply_ai_envelope(db, analysis, raw_envelope)
        except AIServerUnavailable:
            # 폴링 실패 — 현재 DB 상태 그대로 반환 (클라가 다음 주기에 재시도)
            pass

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result=_build_analysis_response(analysis),
    )


# ============================================
# 내부 헬퍼: AI envelope(raw) → Analysis 레코드 반영
# - fetch_ai_job_status() 의 raw 응답을 그대로 받음 (변환 X)
# - 변환은 이 안에서 _transform_ai_to_backend() 로 수행
# - _internal_predicted_stage 가 있으면 ai_result 에 보존 (hospitals.py 추천 점수용)
# ============================================
def _apply_ai_envelope(db: Session, analysis: Analysis, envelope: dict) -> None:
    transformed = _transform_ai_to_backend(envelope) if isinstance(envelope, dict) else {}

    new_status = transformed.get("status")
    if new_status in ("queued", "uploaded", "running"):
        # AI side intermediate state. queued 는 유지, uploaded/running 은 running 으로 정규화.
        if new_status in ("uploaded", "running"):
            analysis.status = "running"
        # queued 그대로
    elif new_status in ("completed", "rejected", "failed"):
        analysis.status = new_status

    # 폴링 envelope 에도 job_id 가 들어옴 → 빈 경우 채움
    raw_job_id = transformed.get("job_id") or envelope.get("job_id")
    if raw_job_id and not analysis.job_id:
        analysis.job_id = raw_job_id

    # ai_result 에 변환 결과 저장 (completed/rejected/failed 만 raw 유의미)
    # running/queued 폴링도 progress 등 부분 업데이트 가능하도록 저장
    ai_result_payload = {
        "prediction": transformed.get("prediction"),
        "recommendation": transformed.get("recommendation"),
        "quality": transformed.get("quality"),
        "progress": transformed.get("progress"),
        "error_message": transformed.get("error_message"),
        "gait_observation_summary": transformed.get("gait_observation_summary"),
    }
    if "_internal_predicted_stage" in transformed:
        ai_result_payload["_internal_predicted_stage"] = transformed["_internal_predicted_stage"]
    analysis.ai_result = ai_result_payload

    # risk_level 별도 컬럼에도 저장 (pets 상세 조회 시 join 비용 감소)
    risk = transformed.get("risk_level")
    if not risk and isinstance(transformed.get("prediction"), dict):
        risk = transformed["prediction"].get("risk_level")
    if risk:
        analysis.risk_level = risk

    if analysis.status in TERMINAL_STATUSES and analysis.completed_at is None:
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
        # 옵션 W: DB 상대경로 그대로 노출. 프론트가 BASE_URL prefix 부착 → legacy_uploads 가 R2 로 302.
        # 모든 status(queued/running/completed/rejected/failed) 응답에서 일관되게 포함되도록 base 에 둠.
        "video_url": analysis.video_url,
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
        # Phase 1 (2026-05-21): 응답 단순화.
        # - prediction 4개 필드만 노출 (decision, risk_level, is_uncertain, display_metrics)
        # - display_metrics 안에서도 analysis_confidence_score 1개만 노출
        # - recommendation, quality 응답 제거 (DB ai_result 에는 raw 보존)
        # - gait_observation_summary 최상위 노출
        raw_pred = ai.get("prediction") or {}
        raw_metrics = raw_pred.get("display_metrics") or {}
        slim_prediction = {
            "decision": raw_pred.get("decision"),
            "risk_level": raw_pred.get("risk_level"),
            "is_uncertain": raw_pred.get("is_uncertain"),
            "display_metrics": {
                "analysis_confidence_score": raw_metrics.get("analysis_confidence_score"),
            },
        }
        base.update(
            {
                "prediction": slim_prediction,
                "gait_observation_summary": ai.get("gait_observation_summary"),
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

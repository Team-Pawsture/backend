"""
영상 분석 관련 API 라우터 (2026-06-02 AI 2단계 분석 구조, 비동기 폴링)
- POST /analyses          : 분석 요청 (JSON {pet_id, video_id, analysis_stage, parent_analysis_id?})
                            · 1차(rear_gate) / 2차(fusion) 분기
- GET  /analyses          : 특정 반려견 분석 이력 (pet_id, 페이지네이션)
- GET  /analyses/recent   : 본인 반려견 최근 completed 목록
- GET  /analyses/{id}     : 분석 결과 조회 (폴링)
- GET  /analyses/{id}/keypoints : 관절 키포인트 시계열 프록시

비동기 폴링 흐름:
  1) POST /analyses → Analysis(status=queued, ai_job_id=None) 생성 + commit (analysis_id 확정)
  2) submit_analysis() 호출 → AI 즉시 queued 응답에서 ai_job_id 수신 → Analysis.ai_job_id 저장
  3) AI 호출 실패 시 status=failed 로 기록 후 503 반환
  4) GET /analyses/{id} 마다 status terminal 아니면 fetch_ai_job_status() 로 폴링
     · AI status(queued/running/succeeded/failed) → 백엔드 status 매핑 후 DB 캐시
     · 폴링 실패(timeout 등) → 현재 DB 상태 그대로 응답 (클라가 재시도)

응답 가공(라우터에서 수행):
  · result.display_metrics : 화면 4영역(슬개골 위험도/재촬영/신뢰도/보행이상) 매핑
  · result.solutions       : decision별 맞춤 솔루션 텍스트
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
    fetch_ai_job_status,
    fetch_keypoints,
    submit_analysis,
)
from app.utils.datetime_helper import to_kst_iso
from app.constants import (
    DECISION_TO_RISK_LEVEL,
    RECAPTURE_REASON_BY_DECISION,
    RECAPTURE_REQUIRED_DECISIONS,
    SIDE_UPLOAD_DECISIONS,
    SOLUTIONS_BY_DECISION,
)
# 2026-05-22 URL 정책 반전: 응답은 상대경로. AI 호출 시 절대 URL 변환은 ai_client 내부 처리.

TERMINAL_STATUSES = ("completed", "rejected", "failed")

# 2026-06-02 AI status → 백엔드 status 매핑
# queued/running 은 그대로, succeeded → completed, failed → failed
_AI_STATUS_MAP = {
    "queued": "queued",
    "running": "running",
    "succeeded": "completed",
    "failed": "failed",
}


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


def _video_or_raise(db: Session, video_id: int, pet: Pet, user_id: int) -> Video:
    """video_id 검증: 존재 + 소유자 일치 + pet_id 일치."""
    video = db.query(Video).filter(Video.video_id == video_id).first()
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
    if video.user_id != user_id:
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
    return video


def _validate_fusion_parent(
    db: Session, parent_analysis_id, user_id: int
) -> tuple[Analysis, str]:
    """
    2차(fusion) 호출용 parent_analysis_id 검증.
    반환: (parent Analysis row, parent 의 ai_job_id)
    조건:
      - parent_analysis_id 존재 (없으면 400)
      - 본인 소유 (PET403)
      - analysis_stage == "rear_gate"
      - status == "completed"
      - result.decision 이 SIDE_UPLOAD_REQUIRED / SIDE_UPLOAD_RECOMMENDED
    """
    if parent_analysis_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"parent_analysis_id": "fusion(2차) 분석에는 parent_analysis_id 가 필요합니다"},
            },
        )

    parent = (
        db.query(Analysis)
        .filter(Analysis.analysis_id == parent_analysis_id)
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"parent_analysis_id": "존재하지 않는 1차 분석입니다"},
            },
        )

    # 본인 소유 확인 (parent pet 의 user_id)
    parent_pet = db.query(Pet).filter(Pet.pet_id == parent.pet_id).first()
    if not parent_pet or parent_pet.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "PET403",
                "message": "접근 권한이 없습니다.",
                "result": None,
            },
        )

    if parent.analysis_stage != "rear_gate":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"parent_analysis_id": "parent 는 1차(rear_gate) 분석이어야 합니다"},
            },
        )

    if parent.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"parent_analysis_id": "1차 분석이 아직 완료되지 않았습니다"},
            },
        )

    # result.decision 확인
    decision = _extract_decision(parent.ai_result)
    if decision not in SIDE_UPLOAD_DECISIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {
                    "parent_analysis_id": "1차 분석 결과가 측면 업로드 대상(SIDE_UPLOAD_REQUIRED/RECOMMENDED)이 아닙니다"
                },
            },
        )

    if not parent.ai_job_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"parent_analysis_id": "1차 분석의 AI job ID 가 없습니다"},
            },
        )

    return parent, parent.ai_job_id


def _extract_decision(ai_result) -> str | None:
    """ai_result(envelope) 에서 result.decision 추출."""
    if not isinstance(ai_result, dict):
        return None
    result = ai_result.get("result")
    if isinstance(result, dict):
        return result.get("decision")
    return None


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
    분석 요청 생성 (2026-06-02 AI 2단계 분석 구조, 비동기 큐잉)
    - 입력: JSON {pet_id, video_id, analysis_stage, parent_analysis_id?}
    - 권한 체크: 본인 반려견만 가능 (PET404/PET403)
    - video_id 검증: 존재 + 소유자 일치 + pet_id 일치
    - 1차(rear_gate): view="rear", parent 없음
    - 2차(fusion): view="side", parent_analysis_id 검증(1차 완료 + 측면 업로드 decision)
    - Analysis(status=queued, ai_job_id=None) 즉시 생성 → AI 큐잉 호출 → ai_job_id 저장
    - 영상 파일은 videos 테이블 소유. 분석 종료 후에도 삭제 X (영구 보존).
    """
    pet = _pet_or_raise(db, payload.pet_id, current_user.user_id)
    video = _video_or_raise(db, payload.video_id, pet, current_user.user_id)

    is_fusion = payload.analysis_stage == "fusion"
    view = "side" if is_fusion else "rear"
    parent: Analysis | None = None
    parent_job_id: str | None = None

    if is_fusion:
        # 2차(fusion): parent_analysis_id 검증
        parent, parent_job_id = _validate_fusion_parent(
            db, payload.parent_analysis_id, current_user.user_id
        )
        # 중복 체크: 같은 parent_analysis_id 로 이미 fusion row 있으면 409
        existing_fusion = (
            db.query(Analysis)
            .filter(Analysis.parent_analysis_id == parent.analysis_id)
            .first()
        )
        if existing_fusion:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "isSuccess": False,
                    "code": "ANALYSIS409",
                    "message": "해당 1차 분석에 대한 2차 분석이 이미 존재합니다.",
                    "result": None,
                },
            )
    else:
        # 1차(rear_gate): 동일 pet_id 에 queued/running 1차 분석 있으면 409
        in_progress = (
            db.query(Analysis)
            .filter(
                Analysis.pet_id == pet.pet_id,
                Analysis.analysis_stage == "rear_gate",
                Analysis.status.in_(["queued", "running"]),
            )
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

    # Analysis 레코드 즉시 생성 (status=queued, ai_job_id 미정)
    new_analysis = Analysis(
        pet_id=pet.pet_id,
        video_id=video.video_id,
        video_url=video.file_url,
        job_id=None,
        ai_job_id=None,
        status="queued",
        analysis_stage=payload.analysis_stage,
        view=view,
        parent_analysis_id=parent.analysis_id if parent else None,
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

    # AI 서버에 분석 요청 (즉시 ai_job_id 수신, 본 분석은 AI 큐에서 비동기 수행)
    try:
        submit_result = await submit_analysis(
            pet_id=pet.pet_id,
            video_id=video.video_id,
            video_url=video.file_url,
            analysis_stage=payload.analysis_stage,
            view=view,
            parent_job_id=parent_job_id,
        )
    except AIServerUnavailable as e:
        new_analysis.status = "failed"
        new_analysis.ai_result = {
            "status": "failed",
            "error": {"code": "AI_SERVER_UNAVAILABLE", "message": f"AI 서버 호출 실패: {e}"},
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

    # ai_job_id + raw envelope 저장
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
            "analysis_stage": new_analysis.analysis_stage,
            "created_at": to_kst_iso(new_analysis.created_at),
        },
    )


# ============================================
# GET /analyses — 특정 반려견의 전체 분석 이력 (페이지네이션, 2026-06-02 P2.5)
# - /{analysis_id} 보다 먼저 등록 (path 충돌 방지 + 가독성)
# - pet_id 소유권 검증은 _pet_or_raise() 재사용 (PET404/PET403)
# - item 스키마는 GET /analyses/{id} 와 동일 (_build_analysis_response 재사용)
#   → display_metrics / solutions 포함. 단, 목록 조회는 AI 폴링 X (DB 캐시 그대로).
# ============================================
@router.get("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def list_analyses_by_pet(
    pet_id: int = Query(..., description="조회 대상 반려견 ID"),
    limit: int = Query(20, ge=1, le=100, description="조회 개수 (1~100, 기본 20)"),
    offset: int = Query(0, ge=0, description="건너뛸 개수 (기본 0)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 반려견의 전체 분석 이력 조회 (페이지네이션)
    - 권한: pet_id 가 본인 소유여야 함 (PET404/PET403, _pet_or_raise 재사용)
    - 정렬: Analysis.created_at DESC (최신순)
    - 페이지네이션: limit/offset. total 은 해당 pet 전체 분석 개수.
    - items: GET /analyses/{id} 와 동일 스키마 (display_metrics, solutions 포함)
    - 분석 0개면 items=[], total=0 (에러 X)
    """
    pet = _pet_or_raise(db, pet_id, current_user.user_id)

    base_query = db.query(Analysis).filter(Analysis.pet_id == pet.pet_id)
    total = base_query.count()

    rows = (
        base_query.order_by(Analysis.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    items = [_build_analysis_response(analysis) for analysis in rows]

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
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
            # 2026-06-02 AI 2단계 분석 구조: 1차/2차 구분
            "analysis_stage": analysis.analysis_stage,
            "view": analysis.view,
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
# - 2026-06-02 AI 2단계 분석 구조: fetch_ai_job_status() 의 raw envelope 를
#   변환 없이 ai_result 에 통째 저장 (P0 — AI 응답 거의 그대로 노출)
# - AI status(queued/running/succeeded/failed) → 백엔드 status 매핑
# ============================================
def _apply_ai_envelope(db: Session, analysis: Analysis, envelope: dict) -> None:
    if not isinstance(envelope, dict):
        return

    ai_status = envelope.get("status")
    new_status = _AI_STATUS_MAP.get(ai_status)
    if new_status:
        analysis.status = new_status

    # 폴링 envelope 에도 job_id 가 들어옴 → 빈 경우 채움
    raw_job_id = envelope.get("job_id")
    if raw_job_id and not analysis.job_id:
        analysis.job_id = raw_job_id

    # ai_result 에 AI envelope 통째 저장 (result / error 포함)
    analysis.ai_result = envelope

    # risk_level 별도 컬럼에도 저장 (recent / pets 상세 join 비용 감소)
    result = envelope.get("result")
    if isinstance(result, dict) and result.get("risk_level"):
        analysis.risk_level = result.get("risk_level")

    if analysis.status in TERMINAL_STATUSES and analysis.completed_at is None:
        analysis.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(analysis)


# ============================================
# 내부 헬퍼: Analysis → 응답 dict (P0 — AI result 거의 그대로 노출)
# - result: AI result 그대로 (succeeded → completed 일 때만)
# - error: AI error 그대로 (failed 일 때만)
# ============================================
def _build_analysis_response(analysis: Analysis) -> dict:
    ai = analysis.ai_result if isinstance(analysis.ai_result, dict) else {}

    result = None
    error = None
    if analysis.status == "completed":
        # AI result 그대로 노출 + P1: display_metrics 추가 (원본 필드는 보존)
        raw_result = ai.get("result")
        if isinstance(raw_result, dict):
            result = {
                **raw_result,
                # P1: 화면 4영역 표시용 가공
                "display_metrics": _build_display_metrics(
                    raw_result, analysis.analysis_stage
                ),
                # P2: decision별 맞춤 솔루션 텍스트
                "solutions": _build_solutions(raw_result),
            }
    elif analysis.status in ("failed", "rejected"):
        raw_error = ai.get("error")
        error = raw_error if isinstance(raw_error, dict) else None

    return {
        "analysis_id": analysis.analysis_id,
        "pet_id": analysis.pet_id,
        "status": analysis.status,
        "analysis_stage": analysis.analysis_stage,
        "view": analysis.view,
        "parent_analysis_id": analysis.parent_analysis_id,
        # 옵션 W: DB 상대경로 그대로 노출. 프론트가 BASE_URL prefix 부착 → legacy_uploads 가 R2 로 302.
        "video_url": analysis.video_url,
        "created_at": to_kst_iso(analysis.created_at),
        "completed_at": to_kst_iso(analysis.completed_at),
        # P0: AI result/error 거의 그대로 노출 (가공은 P1)
        "result": result,
        "error": error,
    }


# ============================================
# P1 내부 헬퍼: AI result → 프론트 화면 4영역 표시용 display_metrics
# - 1) patella_risk      : decision → level (+ 원본 decision_code)
# - 2) recapture_required: decision 기반 value (+ true 일 때 reason)
# - 3) analysis_confidence: scores 스프레드 기반 확신도 (0~100, level)
# - 4) gait_abnormality  : scores.p_screening_abnormal * 100 (0~100, level)
# - 알 수 없는 decision/누락 scores 도 에러 X (fallback). result=None 이면 호출 안 됨.
# ============================================
def _score_level(score: int) -> str:
    """0~100 score → high/moderate/low 공통 변환."""
    if score >= 70:
        return "high"
    if score >= 40:
        return "moderate"
    return "low"


def _build_display_metrics(ai_result: dict, analysis_stage: str) -> dict:
    decision = ai_result.get("decision")
    scores = ai_result.get("scores")
    scores = scores if isinstance(scores, dict) else {}

    # --- 1) patella_risk ---
    # 매핑에 없는 decision 은 fallback "uncertain". decision_code 는 항상 원본 그대로.
    risk_level = DECISION_TO_RISK_LEVEL.get(decision, "uncertain")
    patella_risk = {"level": risk_level, "decision_code": decision}

    # --- 2) recapture_required ---
    recapture_value = decision in RECAPTURE_REQUIRED_DECISIONS
    recapture_required = {"value": recapture_value}
    if recapture_value:
        # decision 별 안내 문구. 매핑 없으면 AI result.message fallback.
        recapture_required["reason"] = (
            RECAPTURE_REASON_BY_DECISION.get(decision)
            or ai_result.get("message")
            or "영상을 다시 촬영해주세요."
        )

    # --- 3) analysis_confidence ---
    # scores 4개 중 최강/최약 신호 차이(spread)가 클수록 확신 높음.
    # 50 + spread*100 → 50~100, 95 로 cap. scores 없으면 score=50(moderate).
    numeric_scores = [v for v in scores.values() if isinstance(v, (int, float))]
    if numeric_scores:
        spread = max(numeric_scores) - min(numeric_scores)
        confidence_score = min(int(50 + spread * 100), 95)
    else:
        confidence_score = 50
    analysis_confidence = {
        "score": confidence_score,
        "level": _score_level(confidence_score),
    }

    # --- 4) gait_abnormality ---
    # 핵심 매핑: p_screening_abnormal(0~1) * 100 → 정수.
    p_screening = scores.get("p_screening_abnormal")
    gait_score = int(p_screening * 100) if isinstance(p_screening, (int, float)) else 0
    gait_abnormality = {
        "score": gait_score,
        "level": _score_level(gait_score),
    }

    return {
        "patella_risk": patella_risk,
        "recapture_required": recapture_required,
        "analysis_confidence": analysis_confidence,
        "gait_abnormality": gait_abnormality,
    }


# ============================================
# P2 내부 헬퍼: AI decision → 맞춤 솔루션 텍스트 배열
# - ai_result 가 dict 아니거나 decision 없으면 빈 배열
# - 매핑에 없는 decision 도 빈 배열 (fallback, 에러 X)
# - 출처: 코넬 수의대, Merck Veterinary Manual, PMC, 서비스 가이드
# ============================================
def _build_solutions(ai_result: dict) -> list:
    if not isinstance(ai_result, dict):
        return []
    decision = ai_result.get("decision")
    if not decision:
        return []
    return SOLUTIONS_BY_DECISION.get(decision, [])

"""
영상 업로드 API — Phase 2 (2026-05-22)
- POST /videos: multipart 업로드 → videos 테이블에 영구 저장
- 응답으로 video_id, video_url, uploaded_at 반환
- 이후 POST /analyses 가 video_id 로 참조

설계 결정 (해성님/나경님 협의 반영):
- 영상은 분석 후에도 영구 보존 (재분석 가능)
- 파일 정리 배치는 별도 백로그
- AI 서버는 video_url 을 HTTP GET 으로 다운로드
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pet import Pet
from app.models.user import User
from app.models.video import Video
from app.schemas.user import CommonResponse
from app.utils.datetime_helper import to_kst_iso
from app.utils.security import get_current_user
# 2026-05-22 URL 정책 반전: DB / 응답 모두 상대경로 저장. AI 호출 시 절대 URL 변환은 ai_client 내부.


router = APIRouter(prefix="/videos", tags=["영상 업로드"])


# ============================================
# 설정값 (Phase 2 신설 — 기존 video_handler 와 분리해 위치 명확화)
# ============================================
VIDEO_UPLOAD_DIR = Path("uploads/videos")
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
# AI 서버 명세 + 기존 video_handler 와 일치
ALLOWED_MIME_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
}
# 확장자 fallback (브라우저가 mime 안 보낼 때)
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi"}


# ============================================
# 헬퍼: pet 소유권 검증 (pets/analyses 라우터와 동일 패턴)
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
# 헬퍼: MIME / 확장자 정규화
# - 반환: 정규화된 확장자 (예: ".mp4"). 미지원 시 None.
# ============================================
def _resolve_extension(filename: str | None, content_type: str | None) -> str | None:
    if content_type and content_type in ALLOWED_MIME_TYPES:
        return ALLOWED_MIME_TYPES[content_type]
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in ALLOWED_EXTENSIONS:
            return ext
    return None


# ============================================
# POST /videos — 영상 업로드 (multipart)
# ============================================
@router.post("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def upload_video(
    pet_id: int = Form(..., description="영상 대상 반려견 ID"),
    video: UploadFile = File(..., description="영상 파일 (mp4/mov/avi, 100MB 이하)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    영상을 영구 저장하고 video_id 를 반환.
    이후 POST /analyses 에서 video_id 로 참조해 분석 요청.
    """
    pet = _pet_or_raise(db, pet_id, current_user.user_id)

    # 1. 파일 첨부 확인
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

    # 2. MIME/확장자 검증
    ext = _resolve_extension(video.filename, video.content_type)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "지원하지 않는 파일 형식입니다. (mp4, mov, avi 만 가능)",
                "result": None,
            },
        )

    # 3. 파일 읽기 + 크기 검증
    contents = await video.read()
    file_size = len(contents)
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "빈 파일입니다.",
                "result": None,
            },
        )
    if file_size > MAX_VIDEO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "파일 크기는 100MB 이하여야 합니다.",
                "result": None,
            },
        )

    # 4. 안전 파일명 + 저장
    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = VIDEO_UPLOAD_DIR / safe_filename
    with open(file_path, "wb") as f:
        f.write(contents)

    # 응답 + DB 모두 상대경로 (URL 정책 반전). 프론트가 도메인 prefix 부착.
    # AI 서버 호출 시점에만 ai_client 가 BASE_URL 붙여 절대 URL 로 변환.
    relative_url = f"/uploads/videos/{safe_filename}"

    # 5. DB row 생성
    # client 가 잘못된 content_type 보내거나(application/octet-stream 등) 비어있으면
    # 확장자로 추정한 표준 MIME 사용 (ALLOWED_MIME_TYPES 에 있는 값만 저장).
    ext_to_mime = {v: k for k, v in ALLOWED_MIME_TYPES.items()}
    if video.content_type in ALLOWED_MIME_TYPES:
        resolved_mime = video.content_type
    else:
        resolved_mime = ext_to_mime.get(ext, "video/mp4")
    new_video = Video(
        pet_id=pet.pet_id,
        user_id=current_user.user_id,
        file_path=str(file_path),
        file_url=relative_url,
        file_size=file_size,
        mime_type=resolved_mime,
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="영상이 업로드되었습니다.",
        result={
            "video_id": new_video.video_id,
            "video_url": new_video.file_url,
            "uploaded_at": to_kst_iso(new_video.uploaded_at),
        },
    )

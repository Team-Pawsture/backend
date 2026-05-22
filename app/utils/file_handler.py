"""
펫 프로필 이미지 업로드/삭제 유틸 (R2 전환, 2026-05-22 단계 C)

- 이미지 파일 검증 (확장자, 크기)
- 안전한 파일명 생성 (충돌 방지)
- Cloudflare R2 업로드 / 삭제

옵션 W (변경 불가 원칙)
- DB pets.profile_image_url : "/uploads/pet_profiles/pet_{pet_id}_{uuid8}{ext}" 형식 유지
- R2 객체 키                : "pet_profiles/pet_{pet_id}_{uuid8}{ext}" (DB 값에서 앞 /uploads/ 제거)
- 응답 형식                 : 변경 없음. url_helper.build_absolute_url 이 R2 public URL 로 치환.
"""

import logging
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.utils import r2_client


logger = logging.getLogger(__name__)


# ============================================
# 설정값
# ============================================
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# 확장자 → 표준 MIME (client 가 잘못된 content_type 보낼 때 fallback)
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
_ALLOWED_MIME_TYPES = set(_EXT_TO_MIME.values())

# R2 객체 키 prefix + DB 저장 시 사용할 상대경로 prefix
# (둘은 의도적으로 분리: r2_client 는 prefix 모름, url_helper 는 상대경로 prefix 만 앎)
_R2_KEY_PREFIX = "pet_profiles/"
_URL_PREFIX = "/uploads/pet_profiles/"


# ============================================
# 파일 형식 검증
# ============================================
def is_allowed_extension(filename: str) -> bool:
    """파일명에서 확장자 추출 후 허용 목록과 비교"""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


# ============================================
# 안전한 파일명 생성
# ============================================
def generate_safe_filename(pet_id: int, original_filename: str) -> str:
    """파일명 충돌 방지를 위한 고유 파일명 생성 — 예: pet_1_a3f2c1d9.jpg"""
    ext = Path(original_filename).suffix.lower()
    unique_id = uuid.uuid4().hex[:8]
    return f"pet_{pet_id}_{unique_id}{ext}"


# ============================================
# 이미지 저장 (R2 업로드)
# ============================================
async def save_pet_image(pet_id: int, file: UploadFile) -> str:
    """
    1. 파일 내용 읽기 (크기 체크 위해 bytes 로 메모리에 올림)
    2. 크기 검증 (10MB 이하)
    3. 안전한 파일명 + R2 객체 키 생성
    4. content_type 확정 (UploadFile 우선, 없으면 확장자 fallback)
    5. R2 업로드
    6. DB 저장용 상대경로 반환 ("/uploads/pet_profiles/{filename}")

    Raises:
        ValueError: 파일 크기/빈 파일 오류 (라우터에서 400 처리)
        r2_client.R2UploadError: R2 업로드 실패 (라우터에서 5xx 처리)
    """
    # 1. 파일 내용 읽기
    contents = await file.read()

    # 2. 크기 검증
    if len(contents) > MAX_FILE_SIZE:
        raise ValueError("파일 크기가 10MB를 초과합니다.")
    if len(contents) == 0:
        raise ValueError("빈 파일입니다.")

    # 3. 안전한 파일명 + R2 키
    safe_filename = generate_safe_filename(pet_id, file.filename)
    r2_key = f"{_R2_KEY_PREFIX}{safe_filename}"

    # 4. content_type 확정
    ext = Path(safe_filename).suffix.lower()
    if file.content_type in _ALLOWED_MIME_TYPES:
        resolved_mime = file.content_type
    else:
        resolved_mime = _EXT_TO_MIME.get(ext, "application/octet-stream")

    # 5. R2 업로드 (실패 시 R2UploadError 그대로 raise → 라우터에서 500 처리)
    await r2_client.upload_file(
        file_obj=contents,
        key=r2_key,
        content_type=resolved_mime,
    )

    # 6. DB 저장용 상대경로 반환 (옵션 W)
    return f"{_URL_PREFIX}{safe_filename}"


# ============================================
# 이미지 삭제 (R2)
# ============================================
async def delete_pet_image(image_url: str | None) -> bool:
    """
    DB 의 profile_image_url 을 받아 R2 객체 삭제.

    동작:
    - image_url 이 None/빈문자열/예상 형식 아님 → no-op, True 반환
    - "/uploads/pet_profiles/{filename}" 또는 R2 키 "pet_profiles/{filename}" 둘 다 처리
    - r2_client.delete_file 은 객체 없어도 True (idempotent)

    실패가 펫 삭제 자체를 막으면 안 됨 → 예외 catch 후 False 반환 (로그만).
    """
    if not image_url:
        return True

    if image_url.startswith(_URL_PREFIX):
        r2_key = _R2_KEY_PREFIX + image_url[len(_URL_PREFIX):]
    elif image_url.startswith(_R2_KEY_PREFIX):
        r2_key = image_url
    else:
        # 예상 외 형식 (구버전 데이터 등). 로그 남기고 통과.
        logger.warning("pet image_url unexpected format, skip R2 delete: %s", image_url)
        return False

    try:
        return await r2_client.delete_file(key=r2_key)
    except Exception as e:
        # delete_file 자체가 예외를 잡아 False 반환하도록 설계됐지만, 방어적으로 한 번 더.
        logger.error("R2 delete unexpected error on pet image: key=%s err=%s", r2_key, e)
        return False

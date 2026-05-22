"""
Cloudflare R2 (S3 호환) 클라이언트 헬퍼

R2 마이그레이션 단계 A — 라우터/파일 핸들러 변경 없이 모듈만 신설.
실제 호출 흐름 연결은 다음 단계.

aioboto3 사용 패턴:
- 세션은 모듈 레벨 1회 생성 (재사용 안전)
- 클라이언트는 매 호출마다 `async with session.client(...)` 컨텍스트로 생성
  (aioboto3 의 client 는 닫힌 후 재사용 불가)

환경변수 (필수)
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_ENDPOINT_URL        (예: https://<account>.r2.cloudflarestorage.com)
- R2_BUCKET_NAME
- R2_PUBLIC_BASE_URL     (R2 public bucket / custom domain. 끝 / 없이)

모듈 import 시점에 위 5개 중 하나라도 비어있으면 ValueError 로 즉시 실패.
(AI_MOCK_MODE 처럼 빈 문자열 default 패턴은 적용하지 않음 — R2 자격증명 누락은 silent fail 위험)
"""

import logging
import os

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# ============================================
# 환경 변수 로드 + 필수 검증
# ============================================
_REQUIRED_ENV_VARS = (
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_BASE_URL",
)


def _load_required_env() -> dict[str, str]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for key in _REQUIRED_ENV_VARS:
        val = os.getenv(key, "")
        if not val:
            missing.append(key)
        values[key] = val
    if missing:
        raise ValueError(
            "R2 환경변수 누락: "
            + ", ".join(missing)
            + ". .env 파일에 모두 채워야 합니다."
        )
    return values


_env = _load_required_env()
R2_ACCESS_KEY_ID = _env["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = _env["R2_SECRET_ACCESS_KEY"]
R2_ENDPOINT_URL = _env["R2_ENDPOINT_URL"].rstrip("/")
R2_BUCKET_NAME = _env["R2_BUCKET_NAME"]
R2_PUBLIC_BASE_URL = _env["R2_PUBLIC_BASE_URL"].rstrip("/")


# ============================================
# aioboto3 세션 (모듈 레벨 1회 생성)
# ============================================
_session = aioboto3.Session()

# R2 는 region 무시. signature v4 명시.
_client_config = Config(signature_version="s3v4", region_name="auto")


def _client_ctx():
    """`async with _client_ctx() as s3:` 패턴으로 사용. 매 호출마다 새 컨텍스트 진입."""
    return _session.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=_client_config,
    )


# ============================================
# 예외
# ============================================
class R2UploadError(Exception):
    """R2 업로드 실패. 라우터에서 5xx 로 변환 권장."""


# ============================================
# 공개 API
# ============================================
async def upload_file(*, file_obj, key: str, content_type: str) -> str:
    """
    R2 에 객체 업로드.

    Args:
        file_obj: file-like 객체 (read() 가능). bytes 도 그대로 전달 가능 (boto3 가 처리).
        key:     R2 객체 키 (예: "videos/abc.mp4", "pet_profiles/pet_1_xxx.jpg").
                 앞 슬래시 권장하지 않음 — 있으면 제거.
        content_type: MIME 타입 (예: "video/mp4", "image/jpeg").

    Returns:
        업로드된 객체 키 (입력 key 와 동일, 앞 슬래시 제거된 형태).

    Raises:
        R2UploadError: 업로드 실패 (네트워크/권한/버킷 미존재 등).
    """
    normalized_key = key.lstrip("/")
    try:
        async with _client_ctx() as s3:
            await s3.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=normalized_key,
                Body=file_obj,
                ContentType=content_type,
            )
    except ClientError as e:
        logger.error("R2 upload failed: key=%s err=%s", normalized_key, e)
        raise R2UploadError(f"R2 업로드 실패 (key={normalized_key}): {e}") from e
    except Exception as e:
        logger.error("R2 upload unexpected error: key=%s err=%s", normalized_key, e)
        raise R2UploadError(f"R2 업로드 중 예외 (key={normalized_key}): {e}") from e

    logger.info("R2 upload ok: key=%s content_type=%s", normalized_key, content_type)
    return normalized_key


async def delete_file(*, key: str) -> bool:
    """
    R2 객체 삭제. idempotent — 객체가 없어도 True.

    Args:
        key: 삭제할 객체 키.

    Returns:
        성공/없음(no-op) 모두 True. 네트워크/권한 오류 시 False.
    """
    normalized_key = key.lstrip("/")
    try:
        async with _client_ctx() as s3:
            await s3.delete_object(Bucket=R2_BUCKET_NAME, Key=normalized_key)
    except ClientError as e:
        # S3 delete_object 는 객체 없어도 204 — 여기 들어오는 건 권한/네트워크/버킷 문제.
        logger.error("R2 delete failed: key=%s err=%s", normalized_key, e)
        return False
    except Exception as e:
        logger.error("R2 delete unexpected error: key=%s err=%s", normalized_key, e)
        return False

    logger.info("R2 delete ok: key=%s", normalized_key)
    return True


def build_public_url(key: str) -> str:
    """R2 public base URL + key 조립. 키 앞 슬래시는 제거."""
    return f"{R2_PUBLIC_BASE_URL}/{key.lstrip('/')}"

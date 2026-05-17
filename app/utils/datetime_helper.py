"""
KST(+09:00) 변환 헬퍼.
- DB는 UTC 유지 (DateTime(timezone=True) + server_default=func.now())
- 응답 직전에 KST로 변환해 명세서 예시와 일치시킴
- date 객체(예: birth_date)는 변환 대상 아님 — 그대로 .isoformat() 사용

사용:
    from app.utils.datetime_helper import to_kst_iso

    "created_at": to_kst_iso(pet.created_at),  # → "2026-05-18T00:30:45.123+09:00"
"""

from datetime import datetime, timedelta, timezone
from typing import Optional


KST = timezone(timedelta(hours=9))


def to_kst_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    datetime → KST(+09:00) ISO 8601 문자열.
    - None 입력 시 None 반환 (호출부의 `if dt else None` 패턴 제거 가능)
    - naive datetime은 UTC로 가정하고 변환 (DB가 server_default=func.now()라 일반적으로 aware지만 안전망)
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).isoformat()

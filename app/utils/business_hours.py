"""
영업시간 처리 유틸리티
- "오늘 영업시간" 추출
- "지금 영업 상태" 판단 (3단계: before_open / open / closed)
- 명세서: 휴무일도 is_open_now="closed", today_hours=null
"""

from datetime import datetime
from typing import Optional


# 요일 매핑 (Python의 weekday(): 월=0, 화=1, ... 일=6)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def get_today_hours_info(business_hours: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """
    business_hours JSON에서 오늘 영업시간 + 영업 상태 추출

    Args:
        business_hours: {
            "monday": {"open": "09:00", "close": "18:30"},
            "thursday": {"closed": true},
            ...
        }

    Returns:
        (today_hours, is_open_now)
        - today_hours: "09:00-18:30" | None
        - is_open_now: "before_open" | "open" | "closed" | None
          · "before_open": 오늘 영업일이지만 아직 시작 전
          · "open": 현재 영업 중
          · "closed": 영업 종료 후 또는 오늘 휴무일
          · None: 영업시간 정보 자체가 없음
    """
    if not business_hours:
        return (None, None)

    now = datetime.now()
    today_key = WEEKDAYS[now.weekday()]

    today_info = business_hours.get(today_key)
    if not today_info:
        return (None, None)

    # 휴무일 — 명세서: is_open_now="closed", today_hours=null
    if today_info.get("closed"):
        return (None, "closed")

    open_str = today_info.get("open")
    close_str = today_info.get("close")
    if not open_str or not close_str:
        return (None, None)

    today_hours = f"{open_str}-{close_str}"

    # 영업 상태 계산 (HH:MM 문자열 비교)
    try:
        now_time = now.strftime("%H:%M")
        if now_time < open_str:
            status = "before_open"
        elif now_time <= close_str:
            status = "open"
        else:
            status = "closed"
    except Exception:
        status = None

    return (today_hours, status)

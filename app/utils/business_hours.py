"""
영업시간 처리 유틸리티
- "오늘 영업시간" 추출
- "지금 영업 상태" 판단 (3단계: before_open / open / closed)
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
        - today_hours: "09:00-18:30" | "휴무" | None
        - is_open_now: "before_open" | "open" | "closed" | None
          (영업시간 정보가 없거나 휴무일이면 None)
    """
    if not business_hours:
        return (None, None)

    now = datetime.now()
    today_key = WEEKDAYS[now.weekday()]

    today_info = business_hours.get(today_key)
    if not today_info:
        return (None, None)

    # 휴무일 — 영업 시작/종료 시각이 없으므로 status는 None
    if today_info.get("closed"):
        return ("휴무", None)

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

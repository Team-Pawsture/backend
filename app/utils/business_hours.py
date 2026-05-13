"""
영업시간 처리 유틸리티
- "오늘 영업시간" 추출
- "지금 영업 중" 여부 판단
"""

from datetime import datetime
from typing import Optional


# 요일 매핑 (Python의 weekday(): 월=0, 화=1, ... 일=6)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def get_today_hours_info(business_hours: Optional[dict]) -> tuple[Optional[str], Optional[bool]]:
    """
    business_hours JSON에서 오늘 영업시간 + 영업 중 여부 추출
    
    Args:
        business_hours: {
            "monday": {"open": "09:00", "close": "18:30"},
            "thursday": {"closed": true},
            ...
        }
    
    Returns:
        (today_hours, is_open_now)
        예: ("09:00-18:30", True), ("휴무", False), (None, None)
    """
    if not business_hours:
        return (None, None)
    
    now = datetime.now()
    today_key = WEEKDAYS[now.weekday()]
    
    today_info = business_hours.get(today_key)
    if not today_info:
        return (None, None)
    
    # 휴무일
    if today_info.get("closed"):
        return ("휴무", False)
    
    open_str = today_info.get("open")
    close_str = today_info.get("close")
    if not open_str or not close_str:
        return (None, None)
    
    today_hours = f"{open_str}-{close_str}"
    
    # 영업 중 여부 계산
    try:
        now_time = now.strftime("%H:%M")
        is_open_now = open_str <= now_time <= close_str
    except Exception:
        is_open_now = None
    
    return (today_hours, is_open_now)
"""
Notification & PushSubscription 관련 Pydantic 스키마
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# 알림 응답 (목록 항목)
# ============================================
class NotificationItem(BaseModel):
    notification_id: int
    type: str
    title: str
    is_read: bool
    related_type: Optional[str]
    related_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 푸시 구독 등록 요청
# ============================================
class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(..., description="브라우저 푸시 엔드포인트 URL")
    p256dh_key: str = Field(..., description="암호화 공개키")
    auth_key: str = Field(..., description="인증키")
    user_agent: Optional[str] = Field(None, description="디바이스 식별 (선택)")


# ============================================
# 푸시 구독 해제 요청
# ============================================
class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(..., description="브라우저 푸시 엔드포인트 URL")
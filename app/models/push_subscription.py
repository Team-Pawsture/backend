"""
PushSubscription 모델 (푸시 알림 구독 정보)
- 브라우저에서 발급받은 PushSubscription 객체 저장
- 1차 배포: 데이터만 저장, 실제 발송 로직은 추후 (pywebpush)
"""

from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.database import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    subscription_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    endpoint = Column(String(500), nullable=False, unique=True, comment="브라우저 푸시 엔드포인트 URL")
    p256dh_key = Column(String(255), nullable=False, comment="암호화 공개키")
    auth_key = Column(String(255), nullable=False, comment="인증키")
    user_agent = Column(String(500), comment="디바이스 식별용 (선택)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
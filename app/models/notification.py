"""
Notification 모델 (알림 테이블)
- ERD v3.2 매핑
- 알림 종류:
  - analysis_complete: 분석 완료
  - high_risk_warning: 위험도 높음 경고
  - weekly_reminder: 주 1회 정기 검진 (위험도 있는 강아지)
  - monthly_reminder: 월 1회 정기 검진 (위험도 없는 강아지)
  - favorite_added: 즐겨찾기 병원 추가
"""

from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    type = Column(String(30), nullable=False, comment="알림 타입 (analysis_complete 등)")
    title = Column(String(200), nullable=False, comment="알림 제목")
    is_read = Column(Boolean, nullable=False, default=False, comment="읽음 여부")
    related_type = Column(String(20), comment="관련 화면 종류 (analysis/pet/hospital)")
    related_id = Column(BigInteger, comment="관련 리소스 ID (클릭 시 이동)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
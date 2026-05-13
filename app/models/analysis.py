"""
Analysis 모델 (영상 분석 테이블)
- ERD v3.2 매핑
- 5/12에 AI 명세 받으면 ai_result 구조 확정
"""

from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    analysis_id = Column(BigInteger, primary_key=True, autoincrement=True)
    pet_id = Column(BigInteger, ForeignKey("pets.pet_id", ondelete="CASCADE"), nullable=False)
    video_url = Column(String(500), nullable=False, comment="업로드된 영상 URL")
    status = Column(String(20), nullable=False, default="pending", comment="pending/processing/completed/failed")
    risk_level = Column(String(20), comment="normal/caution/danger")
    ai_result = Column(JSON, comment="AI 분석 요약 지표")
    memo = Column(String(200), comment="사용자 메모 (0~200자, nullable)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), comment="메모 수정 시 자동 갱신")
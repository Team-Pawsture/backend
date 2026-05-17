"""
Analysis 모델 (영상 분석 테이블)
- 2026-05-17 변경: 명세서 v2 반영
  · status 값: queued / running / completed / rejected / failed
  · job_id 컬럼 추가 (AI 서버 job 추적)
  · completed_at 컬럼 추가 (분석 종료 시각)
  · memo 컬럼 제거 (1차 배포 대상 아님)
"""

from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func

from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    analysis_id = Column(BigInteger, primary_key=True, autoincrement=True)
    pet_id = Column(BigInteger, ForeignKey("pets.pet_id", ondelete="CASCADE"), nullable=False)
    video_url = Column(String(500), nullable=False, comment="업로드된 영상 URL")
    job_id = Column(String(100), nullable=True, comment="AI 서버에서 발급한 job ID")
    status = Column(
        String(20),
        nullable=False,
        default="queued",
        comment="queued/running/completed/rejected/failed",
    )
    risk_level = Column(String(50), nullable=True, comment="AI 위험도 라벨 (예: moderate_suspicion)")
    ai_result = Column(JSON, nullable=True, comment="AI 응답 전체 (prediction, recommendation, quality)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="레코드 갱신 시각 (status 전환 추적용, API 응답에는 비노출)",
    )
    completed_at = Column(DateTime(timezone=True), nullable=True, comment="분석 종료 시각 (completed/rejected/failed)")

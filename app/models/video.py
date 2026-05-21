"""
Video 모델 (영상 영구 저장 테이블) — Phase 2 (2026-05-22)
- POST /videos 로 영상 업로드 시 row 생성
- POST /analyses 가 video_id 로 참조
- 1 video : N analyses 관계 (재분석 가능)
- 분석 종료 후에도 row/파일 보존 (정리는 별도 배치 — 백로그)
"""

from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.database import Base


class Video(Base):
    __tablename__ = "videos"

    video_id = Column(BigInteger, primary_key=True, autoincrement=True)
    pet_id = Column(BigInteger, ForeignKey("pets.pet_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, comment="소유권 검증용")
    file_path = Column(String(500), nullable=False, comment="서버 내부 경로 (uploads/videos/{uuid}.mp4)")
    file_url = Column(String(500), nullable=False, comment="외부 노출 URL ({BASE_URL}/uploads/videos/{uuid}.mp4)")
    file_size = Column(BigInteger, nullable=False, comment="bytes")
    mime_type = Column(String(100), nullable=False, comment="video/mp4 등")
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

"""
Pet 모델 (반려견 테이블)
- ERD v3.2 매핑 (5/7 결정사항 반영)
- 5/13: analyses relationship 추가 (Pet 조회 시 최근 분석 결과 포함용)
"""

from sqlalchemy import Column, BigInteger, String, Date, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Pet(Base):
    __tablename__ = "pets"

    pet_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(20), nullable=False, comment="강아지 이름 (1~20자)")
    birth_date = Column(Date, nullable=False, comment="생년월일")
    breed = Column(String(50), nullable=False, comment="견종 (16종 + 기타 enum)")
    gender = Column(String(10), nullable=False, comment="성별 (male/female)")
    weight = Column(Float, comment="체중 kg (선택)")
    medical_history = Column(String(50), nullable=False, comment="과거 병력 (6개 enum)")
    profile_image_url = Column(String(255), comment="프로필 사진 경로 (nullable)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정
    owner = relationship("User", back_populates="pets")
    analyses = relationship(
        "Analysis",
        backref="pet",
        cascade="all, delete-orphan",
        order_by="desc(Analysis.created_at)",
    )
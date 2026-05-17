"""
Pet 모델 (반려견 테이블)
- 2026-05-17 변경: 명세서 v2 반영
  · medical_history: 단일 string → JSON 배열 (다중 선택)
  · breed_etc, medical_history_etc 컬럼 추가 (OTHER 선택 시 입력)
  · weight: NOT NULL (필수)
"""

from sqlalchemy import Column, BigInteger, String, Date, Float, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Pet(Base):
    __tablename__ = "pets"

    pet_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(20), nullable=False, comment="강아지 이름 (1~20자)")
    birth_date = Column(Date, nullable=False, comment="생년월일")
    breed = Column(String(50), nullable=False, comment="견종 (17종 + OTHER enum, 영문 대문자)")
    breed_etc = Column(String(30), nullable=True, comment="견종이 OTHER일 때 직접 입력값 (1~30자)")
    gender = Column(String(10), nullable=False, comment="성별 (MALE/FEMALE)")
    weight = Column(Float, nullable=False, comment="체중 kg")
    medical_history = Column(JSON, nullable=False, comment="과거 병력 enum 배열 (9개 옵션 중 다중 선택)")
    medical_history_etc = Column(String(100), nullable=True, comment="병력에 OTHER 포함 시 직접 입력값 (1~100자)")
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

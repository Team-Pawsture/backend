"""
Pet 모델 (반려견 테이블)
- ERD v3.1의 pets 테이블 매핑
"""

from sqlalchemy import Column, BigInteger, String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class Pet(Base):
    __tablename__ = "pets"

    pet_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(20), nullable=False, comment="강아지 이름")
    birth_year = Column(Integer, comment="출생연도")
    breed = Column(String(50), comment="견종")
    weight = Column(Float, comment="체중 kg (선택)")
    medical_history = Column(Text, comment="과거 병력 (선택)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정: Pet 1마리 → User 1명
    owner = relationship("User", back_populates="pets")
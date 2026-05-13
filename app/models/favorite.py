"""
FavoriteHospital 모델 (반려견별 즐겨찾기 병원 테이블)
- ERD v3.2 매핑
- 5/7 결정사항: pet 단위로 즐겨찾기 관리 (사용자 단위 X)
"""

from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class FavoriteHospital(Base):
    __tablename__ = "favorite_hospitals"

    favorite_id = Column(BigInteger, primary_key=True, autoincrement=True)
    pet_id = Column(BigInteger, ForeignKey("pets.pet_id", ondelete="CASCADE"), nullable=False)
    hospital_id = Column(BigInteger, ForeignKey("hospitals.hospital_id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 같은 강아지가 같은 병원을 중복 즐겨찾기 못 하도록 제약
    __table_args__ = (
        UniqueConstraint("pet_id", "hospital_id", name="uniq_pet_hospital"),
    )
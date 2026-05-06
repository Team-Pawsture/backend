"""
User 모델 (회원 테이블)
- ERD v3.1의 users 테이블 매핑
"""

from sqlalchemy import Column, BigInteger, String, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(20), unique=True, nullable=False, comment="아이디 (4~20자)")
    password = Column(String, nullable=False, comment="해시된 비밀번호 (bcrypt)")
    name = Column(String(50), nullable=False, comment="보호자 성명")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정: User 1명 ↔ Pet 여러 마리
    pets = relationship("Pet", back_populates="owner", cascade="all, delete-orphan")
"""
Hospital 모델 (병원 테이블)
- ERD v3.2 매핑
- 1차에서는 자체 큐레이션 데이터만 저장 (네이버 API와 매칭용)
"""

from sqlalchemy import Column, BigInteger, String, Float, JSON
from sqlalchemy.orm import relationship

from app.database import Base


class Hospital(Base):
    __tablename__ = "hospitals"

    hospital_id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="병원 이름")
    address = Column(String(255), comment="주소")
    phone = Column(String(20), comment="전화번호")
    latitude = Column(Float, nullable=False, comment="위도")
    longitude = Column(Float, nullable=False, comment="경도")
    specialty = Column(String(50), comment="전문 분야 (자체 큐레이션)")
    image_url = Column(String(500), comment="병원 사진 URL")
    business_hours = Column(JSON, comment="요일별 영업시간 (JSON)")
    certifications = Column(String(255), comment="인증 정보 (피어프리 등)")
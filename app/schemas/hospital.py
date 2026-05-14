"""
Hospital 관련 Pydantic 스키마
- 1차에서는 응답 형태만 정의 (Request body 없음)
"""

from typing import Optional
from pydantic import BaseModel


# ============================================
# 병원 리스트 - 항목
# ============================================
class HospitalItem(BaseModel):
    hospital_id: Optional[int]  # 자체 DB에 매칭된 경우만 ID 있음
    name: str
    address: Optional[str]
    phone: Optional[str]
    latitude: float
    longitude: float
    distance_meters: Optional[int]
    duration_seconds: Optional[int]
    specialty: Optional[str]
    certifications: list[str] = []
    image_url: Optional[str]
    today_hours: Optional[str]
    is_open_now: Optional[str]  # "before_open" | "open" | "closed" | None


# ============================================
# 병원 상세
# ============================================
class HospitalDetail(BaseModel):
    hospital_id: Optional[int]
    name: str
    address: Optional[str]
    phone: Optional[str]
    latitude: float
    longitude: float
    specialty: Optional[str]
    certifications: list[str] = []
    image_url: Optional[str]
    business_hours: Optional[dict]
    today_hours: Optional[str]
    is_open_now: Optional[str]  # "before_open" | "open" | "closed" | None
    distance_meters: Optional[int]
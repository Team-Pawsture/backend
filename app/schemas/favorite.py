"""
FavoriteHospital 관련 Pydantic 스키마
- 즐겨찾기 추가/해제/목록 조회 응답
- 5/7 결정사항: pet 단위로 즐겨찾기 관리
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


# ============================================
# 즐겨찾기 추가 응답
# ============================================
class FavoriteAddResponse(BaseModel):
    favorite_id: int
    pet_id: int
    hospital_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 즐겨찾기 해제 응답
# ============================================
class FavoriteDeleteResponse(BaseModel):
    pet_id: int
    hospital_id: int
    deleted: bool


# ============================================
# 즐겨찾기 목록 - 병원 정보 (JOIN 결과)
# ============================================
class FavoriteHospitalItem(BaseModel):
    favorite_id: int
    hospital_id: int
    name: str
    address: Optional[str]
    phone: Optional[str]
    image_url: Optional[str]
    added_at: datetime


# ============================================
# 즐겨찾기 목록 응답
# ============================================
class FavoriteListResponse(BaseModel):
    pet_id: int
    pet_name: str
    total: int
    favorites: list[FavoriteHospitalItem]
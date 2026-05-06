"""
Pet 관련 Pydantic 스키마
- 요청(Request) / 응답(Response) 데이터의 형식과 유효성 검사 정의
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# 반려견 등록 요청 (Request Body)
# ============================================
class PetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20, description="강아지 이름")
    birth_year: int = Field(..., ge=2000, le=2030, description="출생연도 (2000~2030)")
    breed: str = Field(..., min_length=1, max_length=50, description="견종")
    weight: Optional[float] = Field(None, gt=0, description="체중 kg (선택)")
    medical_history: Optional[str] = Field(None, max_length=1000, description="과거 병력 (선택)")


# ============================================
# 반려견 응답 (Response)
# ============================================
class PetResponse(BaseModel):
    pet_id: int
    name: str
    birth_year: int
    breed: str
    weight: Optional[float]
    medical_history: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================
# 반려견 목록용 응답 (간단 버전)
# ============================================
class PetSimpleResponse(BaseModel):
    pet_id: int
    name: str
    birth_year: int
    breed: str
    weight: Optional[float]

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 반려견 정보 수정 요청 (모든 필드 선택적)
# ============================================
class PetUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=20, description="강아지 이름")
    birth_year: Optional[int] = Field(None, ge=2000, le=2030, description="출생연도")
    breed: Optional[str] = Field(None, min_length=1, max_length=50, description="견종")
    weight: Optional[float] = Field(None, gt=0, description="체중 kg")
    medical_history: Optional[str] = Field(None, max_length=1000, description="과거 병력")
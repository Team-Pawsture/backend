"""
Pet 관련 Pydantic 스키마
- 2026-05-17 변경: 명세서 v2 반영
  · enum 영문 대문자: 견종 17종 + OTHER, 병력 9개, 성별 MALE/FEMALE
  · medical_history: 배열 (다중 선택)
  · breed_etc, medical_history_etc 필드 추가
  · weight 필수
  · NONE + 다른 항목 동시 선택 차단 검증
"""

from datetime import date
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ============================================
# Literal 타입 정의 (영문 대문자)
# - 변경 시 app/constants.py 도 함께 수정 필요!
# ============================================

DogBreed = Literal[
    "POMERANIAN", "MALTESE", "TOY_POODLE", "MINIATURE_POODLE", "CHIHUAHUA",
    "YORKSHIRE_TERRIER", "SHIH_TZU", "BICHON_FRISE", "PEKINGESE", "MINIATURE_PINSCHER",
    "PAPILLON", "COCKER_SPANIEL",
    "BOSTON_TERRIER", "JACK_RUSSELL_TERRIER", "DACHSHUND", "FRENCH_BULLDOG", "PUG",
    "OTHER",
]

MedicalHistoryItem = Literal[
    "NONE",
    "PATELLA_LUXATION_DIAGNOSED",
    "PATELLA_SURGERY",
    "HIP_DYSPLASIA",
    "CRUCIATE_LIGAMENT_INJURY",
    "DISC",
    "ARTHRITIS",
    "OBESITY",
    "OTHER",
]

Gender = Literal["MALE", "FEMALE"]


# ============================================
# 반려견 등록 (POST /pets)
# - multipart/form-data로 받기 때문에 라우터에서 Form(...)으로 직접 검증
# - medical_history는 form에서 콤마 구분 문자열로 받아 라우터에서 list로 파싱
# ============================================


# ============================================
# 반려견 정보 수정 요청 (PUT /pets/{pet_id})
# - 모든 필드 선택적 (부분 수정)
# - 비즈니스 검증(NONE/OTHER/etc 동반)은 라우터(pets.py) 에서 직접 처리
#   → result 의 필드명("medical_history" 등)이 명세서와 정확히 일치하도록 유지
#   → model_validator 사용 시 loc=("body",) 로 잡혀 필드명 추적 불가
# ============================================
class PetUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=20, description="강아지 이름")
    birth_date: Optional[date] = Field(None, description="생년월일 (YYYY-MM-DD)")
    breed: Optional[DogBreed] = Field(None, description="견종 (17종 + OTHER)")
    breed_etc: Optional[str] = Field(None, min_length=1, max_length=30, description="breed=OTHER일 때 직접 입력값")
    gender: Optional[Gender] = Field(None, description="성별 (MALE/FEMALE)")
    weight: Optional[float] = Field(None, gt=0, description="체중 kg")
    medical_history: Optional[List[MedicalHistoryItem]] = Field(
        None, description="과거 병력 배열 (최소 1개)"
    )
    medical_history_etc: Optional[str] = Field(
        None, min_length=1, max_length=100, description="medical_history에 OTHER 포함 시 직접 입력값"
    )

"""
Pet 관련 Pydantic 스키마
- 요청(Request) / 응답(Response) 데이터의 형식과 유효성 검사 정의
- 5/7 결정사항: enum 적용 (견종 16종 + 기타, 병력 6개, 성별 2개)
- enum 옵션은 app/constants.py에서 통합 관리
- ⚠️ Python 3.10 호환성: Literal에 변수 unpacking 불가 → 직접 박음
- 5/13: LatestAnalysisResponse 추가 (병원 추천 API 입력용)
"""

from datetime import datetime, date
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Literal 타입 정의
# ⚠️ Python 3.10 호환성으로 인해 직접 박음
# 변경 시 app/constants.py 도 함께 수정 필요!
# ============================================

DogBreed = Literal[
    "포메라니안", "말티즈", "토이푸들", "미니어처푸들", "치와와",
    "요크셔테리어", "시츄", "비숑프리제", "페키니즈", "미니핀",
    "빠삐용", "코카스파니엘",
    "보스턴테리어", "잭러셀테리어", "닥스훈트", "프렌치불독",
    "기타"
]

MedicalHistory = Literal[
    "없음",
    "슬개골 탈구 이력 있음",
    "슬개골 수술 경험 있음",
    "관절 질환 (슬개골 외)",
    "근육/인대 부상 이력",
    "기타"
]

Gender = Literal["male", "female"]


# ============================================
# 반려견 등록 요청 (Request Body)
# ============================================
class PetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20, description="강아지 이름")
    birth_date: date = Field(..., description="생년월일 (YYYY-MM-DD)")
    breed: DogBreed = Field(..., description="견종 (16종 + 기타)")
    gender: Gender = Field(..., description="성별 (male/female)")
    weight: Optional[float] = Field(None, gt=0, description="체중 kg (선택)")
    medical_history: MedicalHistory = Field(..., description="과거 병력 (6개 enum)")


# ============================================
# 최근 분석 결과 (병원 추천 API 입력용) ⭐ 5/13 추가
# - AI 명세서 응답에서 핵심 필드만 추출
# - 분석 이력이 없으면 latest_analysis = null
# ============================================
class LatestAnalysisResponse(BaseModel):
    analysis_id: int
    status: str = Field(..., description="queued/running/completed/rejected/failed")
    risk_level: Optional[str] = Field(None, description="AI 위험도 라벨 (예: moderate_suspicion)")
    predicted_stage: Optional[int] = Field(None, description="예측 단계 (1~4)")
    estimated_stage: Optional[str] = Field(None, description="예측 단계 한글 표현 (예: '2기 의심')")
    confidence: Optional[float] = Field(None, description="AI 신뢰도 (0~1)")
    summary: Optional[str] = Field(None, description="분석 결과 요약 문장")
    analyzed_at: datetime = Field(..., description="분석 생성 시각")

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 반려견 응답 (Response - 상세)
# - 5/13: latest_analysis 필드 추가
# ============================================
class PetResponse(BaseModel):
    pet_id: int
    name: str
    birth_date: date
    breed: str
    gender: str
    weight: Optional[float]
    medical_history: str
    profile_image_url: Optional[str]
    created_at: datetime
    latest_analysis: Optional[LatestAnalysisResponse] = Field(
        None, description="가장 최근 분석 결과 (없으면 null)"
    )

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 반려견 목록용 응답 (간단 버전)
# ============================================
class PetSimpleResponse(BaseModel):
    pet_id: int
    name: str
    birth_date: date
    breed: str
    gender: str
    weight: Optional[float]
    profile_image_url: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 반려견 정보 수정 요청 (모든 필드 선택적)
# ============================================
class PetUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=20, description="강아지 이름")
    birth_date: Optional[date] = Field(None, description="생년월일 (YYYY-MM-DD)")
    breed: Optional[DogBreed] = Field(None, description="견종")
    gender: Optional[Gender] = Field(None, description="성별 (male/female)")
    weight: Optional[float] = Field(None, gt=0, description="체중 kg")
    medical_history: Optional[MedicalHistory] = Field(None, description="과거 병력")
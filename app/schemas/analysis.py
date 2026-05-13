"""
Analysis 관련 Pydantic 스키마
- 메모 작성/수정 요청 및 응답
- 5/12에 영상 분석 요청/조회 스키마 추가 예정
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# 분석 메모 작성 요청 (PATCH /analyses/{id}/memo)
# ============================================
class AnalysisMemoRequest(BaseModel):
    memo: str = Field(..., max_length=200, description="사용자 메모 (0~200자, 빈 문자열 시 메모 삭제)")


# ============================================
# 분석 메모 응답
# ============================================
class AnalysisMemoResponse(BaseModel):
    analysis_id: int
    memo: Optional[str]
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
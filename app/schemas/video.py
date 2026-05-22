"""
Video 관련 Pydantic 스키마 — Phase 2 (2026-05-22)
- POST /videos: multipart 입력 → Form/File 직접 받아 라우터에서 검증 (스키마 클래스 없음)
- 응답은 라우터가 dict 빌드 (다른 라우터와 동일 컨벤션)
- POST /analyses: JSON body 입력 → AnalysisCreateRequest 사용
"""

from pydantic import BaseModel, Field


# ============================================
# POST /analyses 신규 JSON 입력
# - 기존 multipart (pet_id form + video file) 폐기
# - video_id 는 사전에 POST /videos 로 업로드해서 받은 ID
# ============================================
class AnalysisCreateRequest(BaseModel):
    pet_id: int = Field(..., description="분석 대상 반려견 ID")
    video_id: int = Field(..., description="POST /videos 로 사전 업로드한 영상 ID")

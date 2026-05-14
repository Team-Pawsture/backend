"""
영상 분석 관련 API 라우터
- (5/17 이후 예정) POST /analyses : 영상 분석 요청 (memo 필드 통합 예정)
- (5/17 이후 예정) GET /analyses/{analysis_id} : 분석 결과 조회
"""

from fastapi import APIRouter


router = APIRouter(prefix="/analyses", tags=["영상 분석"])

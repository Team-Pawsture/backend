"""
Analysis 관련 Pydantic 스키마
- 2026-05-17: 명세서 v2 기준으로 신규 작성
  · POST /analyses: multipart/form-data (pet_id + video) → 스키마 없음 (라우터에서 Form/File)
  · GET /analyses/{analysis_id}: status에 따라 응답 필드 다름 (라우터에서 동적 구성)
"""

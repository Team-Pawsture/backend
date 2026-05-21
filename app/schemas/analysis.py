"""
Analysis 관련 Pydantic 스키마
- 2026-05-17: 명세서 v2 기준으로 신규 작성
  · POST /analyses: multipart/form-data (pet_id + video) → 스키마 없음 (라우터에서 Form/File)
  · GET /analyses/{analysis_id}: status에 따라 응답 필드 다름 (라우터에서 동적 구성)
- 2026-05-18 P5: prediction 응답 확장 (display_metrics, is_uncertain, is_high_risk, user_message)
- 2026-05-21 Phase 1: completed 응답 단순화 + gait_observation_summary 신규
  · prediction 노출 필드만: decision / risk_level / is_uncertain / display_metrics
  · display_metrics 노출 필드만: analysis_confidence_score
  · recommendation / quality 응답 제거 (DB ai_result 에는 raw 보존)
  · gait_observation_summary (string | null) 최상위 노출
    - 위치 근거: 해성님 카톡 표기 그대로 (prediction.xxx 아님)
    - 생성 로직: app/utils/ai_client.py:build_gait_observation_summary

라우터가 응답 dict를 직접 구성하므로 본 모듈에는 클래스 정의 없음.
응답 포맷 변환은 app/utils/ai_client.py:_transform_ai_to_backend +
app/routers/analyses.py:_build_analysis_response 에 분산.
"""

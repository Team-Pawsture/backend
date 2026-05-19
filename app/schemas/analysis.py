"""
Analysis 관련 Pydantic 스키마
- 2026-05-17: 명세서 v2 기준으로 신규 작성
  · POST /analyses: multipart/form-data (pet_id + video) → 스키마 없음 (라우터에서 Form/File)
  · GET /analyses/{analysis_id}: status에 따라 응답 필드 다름 (라우터에서 동적 구성)
- 2026-05-18 P5: prediction 응답 확장
  · is_uncertain (boolean) — AI 판단 불확실 여부
  · is_high_risk (boolean) — 고위험 가능 신호 감지 여부
  · user_message (string | null) — AI 안내 메시지 (recommendation.summary 와 동일 소스)
  · display_metrics (object | null):
      - suspicious_signal_score (number)
      - abnormal_signal_score (number)
      - analysis_confidence_score (number | null)
      - analysis_confidence_level ("high" | "medium" | "low" | "unknown")
  · 기존 필드(predicted_stage / estimated_stage / class_probabilities)는 의료 안전 정책상 null 유지
    → 매핑 확정은 백로그 BL-5 참고

라우터가 응답 dict를 직접 구성하므로 본 모듈에는 클래스 정의 없음.
응답 포맷 변환은 app/utils/ai_client.py:_transform_ai_to_backend 에 집중.
"""

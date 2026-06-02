"""
Analysis 관련 Pydantic 스키마

- POST /analyses 요청 스키마는 app/schemas/video.py:AnalysisCreateRequest 사용.
- GET /analyses, GET /analyses/{analysis_id} 응답은 status/단계에 따라 필드가 달라
  라우터(app/routers/analyses.py)가 응답 dict 를 직접 구성한다.
  · status 매핑 + display_metrics(화면 4영역) + solutions 가공: _build_analysis_response /
    _build_display_metrics / _build_solutions (모두 app/routers/analyses.py).

따라서 본 모듈에는 별도 클래스 정의가 없다 (요청 스키마는 video.py, 응답은 라우터 구성).
"""

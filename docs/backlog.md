# 백로그 — 후속 작업 후보 메모

명세서 1차 구현 중 발견됐지만 현재 스코프 밖이거나, 별도 결정/협의가 필요한 항목.
신규 발견 시 위에 추가. 처리되면 해당 항목 제거 또는 "완료" 표시.

**우선순위 가이드**
- **P0** — 운영 배포 차단 요소. 도메인/정책 확정되면 즉시 적용.
- **P1** — 운영 안정성/일관성 위해 배포 후 단기간(1~2주) 내 작업.
- **P2** — 확장/협의 시점에 작업. 트리거 조건 발생 시까지 보류 가능.

---

## BL-1 · 자체 DB 병원 seed 부족 + 카카오 매칭 휴리스틱 한계

**우선순위**: P1
**트리거**: 1차 배포 직후. 사용자가 추천 결과를 받기 시작하는 시점부터 매칭률 0%가 곧바로 UX 문제로 드러남.
**발견 시점**: 2026-05-18 (P2 통합 검증)

**현황**
- 강남 좌표(37.4935, 127.0245)로 `POST /hospitals/recommend` 호출 시 카카오 결과 45건 vs 자체 DB `hospitals` 3건
- 매칭 휴리스틱(`app/routers/hospitals.py:_match_with_local_db`)이 "이름 부분 일치 + 좌표 0.001 이내(~100m)"라 너무 빡빡 → 강남 좌표에서 매칭 0건 확인
- 결과적으로 응답의 `specialty`/`certifications`/`today_hours`/`hospital_id` 모두 null

**영향**
- `POST /hospitals/recommend`의 specialty 기반 +40 가중치가 실제 호출에서 거의 발동 안 함
  (P2 단위 테스트와 hospital 3 임시 수정으로 기능 자체는 정상 동작 확인 완료)
- 프론트가 "상세보기" 버튼 비활성화 권장(명세) → 거의 모든 카드가 비활성

**후보 액션**
- 자체 DB seed 데이터 확대 (주요 도시 정형외과 동물병원 50~100건)
- 매칭 휴리스틱 완화 (좌표 200~300m, 이름 공백/특수문자 정규화 후 토큰 부분 매칭)
- 또는 카카오 `place_id`를 자체 DB에 컬럼 추가해 ID 매칭으로 전환 (가장 견고)

**관련 코드**
- `app/routers/hospitals.py:_match_with_local_db` (휴리스틱 위치)
- `app/models/hospital.py` (place_id 컬럼 추가 검토)

---

## BL-2 · `specialty` 어휘 표준화

**우선순위**: P2
**트리거**: BL-1 진행과 묶어서. seed 데이터 확대 시 어휘 통일이 강제됨 → 그 시점에 PM과 enum 확정.
**발견 시점**: 2026-05-18 (P2 검증)

**현황**
- 자체 DB `hospitals.specialty`가 자유 문자열로 입력됨 (현 seed: "정형외과", "내과", "슬개골 전문")
- 명세서 +40 가중치 트리거 조건은 정확히 `specialty == "정형외과"` 한 문자열만 매칭
- 결과: hospital 3("슬개골 전문") 같은 슬개골 특화 병원이 +40 못 받음

**영향**
- 추천 우선순위가 PM 의도와 어긋날 가능성 (슬개골 특화 병원을 일반 정형외과보다 낮게 평가)

**후보 액션**
- PM과 specialty 어휘 표준화 협의 (예: enum `ORTHOPEDICS / INTERNAL / PATELLA_SPECIALTY / ...`)
- 또는 +40 트리거 조건을 집합으로 확장: `specialty in {"정형외과", "슬개골 전문"}`
- 표준화 후 자체 DB seed 일괄 정규화 마이그레이션 필요

**관련 코드**
- `app/routers/hospitals.py:_compute_recommend_score` (트리거 조건)
- `app/models/hospital.py` (Column 정의)

---

## BL-3 · favorites / notifications 라우터 활성화 시 KST 변환 적용

**우선순위**: P2
**트리거**: 1차 배포 제외된 favorites/notifications/push 라우터를 활성화하는 시점.
즉, `app/main.py:91-93` 의 `# app.include_router(...)` 세 줄을 푸는 PR과 같이 처리.
**발견 시점**: 2026-05-18 (P4 grep 범위 확인 중)

**현황**
- P4에서 활성 라우터(auth/pets/analyses) 8곳의 `datetime.isoformat()` 을 `to_kst_iso()` 로 일괄 교체
- 비활성 라우터는 그대로 둠:
  - `app/routers/favorites.py:127` (`new_favorite.created_at.isoformat()`)
  - `app/routers/favorites.py:231` (`fav.created_at.isoformat()`)
  - `app/routers/notifications.py:61` (`n.created_at.isoformat()`)

**영향**
- 활성화 PR에서 빼먹으면 응답 timezone이 라우터별로 들쭉날쭉 (UTC vs KST) → 프론트 표시 일관성 깨짐.

**후보 액션**
- 활성화 PR 체크리스트에 "datetime 응답 → `to_kst_iso` 사용" 항목 추가
- 필요 시 `app/utils/datetime_helper.py` import 후 3곳 교체 (작업 자체는 5분 이내)

**관련 코드**
- `app/utils/datetime_helper.py:to_kst_iso`
- `app/main.py:91-93` (라우터 활성화 지점)

---

## BL-4 · BackgroundTasks → Celery/RQ 전환

**우선순위**: P2
**트리거**: 다음 중 하나라도 정기 발생 시
- 동시 진행 분석 5건 이상 (일/주 단위 빈도 측정)
- 워커 재시작/크래시 시 잔존 queued 분석이 자주 발견 (BL-6 모니터링과 연계)
- 멀티 워커(`uvicorn --workers N>1`) 또는 멀티 인스턴스 배포 필요
**발견 시점**: 2026-05-17 (P1 설계 단계)

**현황**
- AI 호출이 평균 34초/최대 72초 동기라 FastAPI `BackgroundTasks`로 비동기 처리 중
  (`app/routers/analyses.py:_run_analysis_in_background`)
- BackgroundTasks는 응답 직후 같은 워커 프로세스에서 실행 → 워커 죽으면 분실, 추적 불가
- 1차 배포 수준(사용자 수십명, 동시 분석 거의 없음)에서는 수용

**영향**
- 워커 재시작 시 진행 중 분석이 영구 queued로 남을 수 있음 (BL-6로 부분 완화)
- 멀티 워커 배포 시 분석이 어느 워커에서 실행됐는지 추적 불가, 워커 간 부하 불균형
- 동시 분석 누적 시 이벤트 루프 점유로 다른 요청 응답 지연 가능

**후보 액션**
- Celery + Redis (또는 RQ) 도입 → 분석 큐 분리
- Analysis 레코드에 worker_id/task_id 컬럼 추가해 추적성 확보
- 재시도 정책 (네트워크 실패 시 3회 자동 재시도 등) 도입

**관련 코드**
- `app/utils/ai_client.py:11-23` (docstring에 전환 트리거 명시)
- `app/routers/analyses.py:_run_analysis_in_background` (현재 BG 함수)

---

## BL-5 · AI 응답 매핑 TODO 해소 (AI팀과 협의)

**우선순위**: P1
**트리거**: AI팀과 협의 가능한 시점부터. 운영 배포 전에 매핑 정책 확정 권장 — 의료 정보를 임시 추론으로 노출할 수 없는 정책이라, 노출 필드들이 계속 null이면 프론트 UI에 공백이 생김.
**발견 시점**: 2026-05-17 (P1 설계 단계, AI 명세 v3 분석)

**현황**
- AI 서버는 `decision` / `risk_level` / `probabilities`(3종) 만 제공
- 백엔드 명세는 `predicted_stage`(1~4) / `estimated_stage`("2기 의심") / `class_probabilities`(normal+stage1~4) / `quality.score` 같은 추가 필드를 기대
- 의료 정보 안전 정책에 따라 위 필드는 모두 `null` + TODO 주석으로 보존
  (`app/utils/ai_client.py:_transform_ai_to_backend`)
- `recommendation.action` 도 동일 사유로 `null` (AI는 `user_message` 하나만 제공)
- `risk_level` 어휘 불일치 — AI는 `suspicious/uncertain/...`, 명세 예시는 `moderate_suspicion`

**영향**
- 프론트가 위 필드를 표시 못 함 (단계 라벨, 5단계 확률 차트 등 UX 누락)
- 병원 추천 +40 가중치는 내부 매핑(`AI_INTERNAL_STAGE_MAPPING`)으로 우회 동작 중이나 임시방편

**후보 액션 (AI팀과 협의 항목)**
- decision → predicted_stage(1~4) 공식 매핑 합의
- decision → estimated_stage 한글 라벨 합의
- AI probabilities(3종) → class_probabilities(5단계) 변환 규칙 또는 AI에 5단계 출력 추가 요청
- quality.score 노출 정책 (현재 AI 응답에 없음)
- user_message를 summary/action으로 분리 또는 AI 응답에 action 필드 추가 요청
- risk_level 어휘를 백엔드/AI 양측에서 통일

**관련 코드**
- `app/utils/ai_client.py:_transform_ai_to_backend` (TODO 주석 5개 위치)
- 매핑 확정 후 `AI_INTERNAL_STAGE_MAPPING` 환경변수 제거 + 응답 노출로 이전

---

## BL-6 · 1시간+ queued 잔존 분석 정리 배치

**우선순위**: P1
**트리거**: 운영 배포 직후 1주 내. BackgroundTasks 한계(BL-4) 보완용 안전망이므로 가능한 빨리 도입.
**발견 시점**: 2026-05-17 (P1 설계 단계)

**현황**
- POST /analyses 요청은 Analysis(status=queued) 즉시 생성 + BackgroundTask 등록
- 백그라운드 함수가 정상 종료 시 status=completed/rejected/failed 로 갱신
- 워커 크래시/재시작 시 BG 함수가 안 돌아 status=queued 가 영구 잔존 가능
- 잔존 queued 행은 partial unique index 때문에 같은 pet의 새 분석 요청을 차단(409)

**영향**
- 사용자가 분석 무한 대기 (프론트는 폴링 계속)
- 같은 pet으로 재시도해도 409 → 사용자 차단

**후보 액션**
- 별도 스크립트 또는 APScheduler/cron 으로 주기 실행:
  ```
  UPDATE analyses
  SET status='failed',
      ai_result = jsonb_set(...'{error_message}', '"워커 종료로 분석 분실"'),
      completed_at = NOW()
  WHERE status IN ('queued','running')
    AND created_at < NOW() - INTERVAL '1 hour';
  ```
- 영상 파일도 함께 정리 (`uploads/analysis_videos/` orphan)
- 가능하면 Celery 전환(BL-4) 시 자체 재시도/타임아웃 메커니즘으로 대체

**관련 코드**
- `app/models/analysis.py` (status/created_at 컬럼)
- `app/routers/analyses.py:_run_analysis_in_background` (정상 흐름 비교용)

---

## BL-7 · CORS `allow_origins` 운영 도메인 제한

**우선순위**: P0
**트리거**: 운영 배포 차단 요소. 프론트 도메인이 확정되면 즉시 적용 — 절대 와일드카드(`*`)로 배포 금지.
**발견 시점**: 2026-05-18 (전체 작업 정리 중)

**현황**
- `app/main.py:27-32` 의 CORS 설정이 개발 편의상 `allow_origins=["*"]`
- `allow_credentials=True` 와 `allow_origins=["*"]` 조합은 브라우저가 차단(스펙상)하지만, 인증 토큰 노출 등 보안 표면이 넓어짐

**영향**
- 임의 도메인에서 API 호출 가능 → 토큰 탈취 시 다른 도메인에서도 사용 가능
- 1차 배포 시점부터 HTTPS와 같이 잠가야 함 (배포 후 변경은 회귀 위험 큼)

**후보 액션**
- 프론트 운영 도메인 확정 후 `allow_origins=["https://www.pasture.com", "https://pasture.com"]` 등으로 명시
- 개발/스테이징은 환경변수 `CORS_ORIGINS` 로 분리하면 더 안전
- 배포 PR 체크리스트에 "CORS 제한 확인" 항목 추가

**관련 코드**
- `app/main.py:27-32` (CORS 미들웨어 등록)

---

## BL-8 · AI `display_metrics` 미구현 (analysis_confidence_score/level)

**우선순위**: P2
**트리거**: AI 모델 패키지 업그레이드 시점 (현재 `v3_two_stage_policy_9_5`).
AI팀이 `display_metrics` 또는 `analysis_confidence_*` 산출 로직을 추가할 때 백엔드 fallback 제거.
**발견 시점**: 2026-05-19 (P8 실연동 검증)

**현황**
- AI 명세서상 prediction 응답에 `display_metrics` 객체 정의되어 있으나, 실제 모델 패키지(v3_two_stage_policy_9_5)는 미산출
- AI raw response 트리 전체 검색 결과: `display_metrics`, `suspicious_signal_score`,
  `abnormal_signal_score`, `analysis_confidence_score`, `analysis_confidence_level` 모두 NOT FOUND
- 모델 자체 `policy_output_keys` 에도 해당 키 없음

**현재 백엔드 처리** (`app/utils/ai_client.py:_build_display_metrics`)
- AI가 `display_metrics` 보내면 그대로 사용 (4개 필드만 추림)
- 안 보내면 fallback derive:
  · `suspicious_signal_score` = `round(prob_target_suspicious * 100, 1)`
  · `abnormal_signal_score`   = `round(prob_target_abnormal * 100, 1)`
  · `analysis_confidence_score` = `null` (AI 미산출)
  · `analysis_confidence_level` = `"unknown"`
- AI 가 향후 직접 보내기 시작하면 자동으로 AI 값 우선 적용됨 (코드 변경 불필요)

**영향**
- 프론트의 "분석 신뢰도" 표시가 항상 `unknown` / null 로 노출
- suspicious/abnormal score 는 백엔드 derive 값이라 AI 의도와 다를 수 있음 (스케일 정책 변경 시 갱신 필요)

**후보 액션**
- AI팀과 협의: `analysis_confidence_score` 산출 정책 확정 (예: 모델 entropy, max prob, calibration 등)
- 또는 모델 패키지 새 버전에 `display_metrics` 출력 추가 요청
- 구현 완료되면 `_build_display_metrics` 의 derive 분기 단순화 (또는 그대로 두고 안전망으로 유지)

**관련 코드**
- `app/utils/ai_client.py:_build_display_metrics` (현재 매핑/fallback 위치)
- `app/utils/ai_client.py:_transform_ai_to_backend` (호출 지점)

---

## BL-9 · keypoints 응답의 빈 프레임 / null joint 처리 가이드

**우선순위**: P3 (정보 공유 차원)
**트리거**: 프론트 스켈레톤 애니메이션 구현 시작 시. 나경님과 사전 공유 권장.
**발견 시점**: 2026-05-19 (P8 실연동 검증, analysis_id=23 keypoints 호출)

**현황**
- `GET /analyses/{id}/keypoints` 응답은 AI 응답을 변환 없이 통과 (의도된 동작)
- AI가 키포인트 추출에 실패한 프레임은 `keypoints` 가 빈 객체 `{}` 로 반환됨
- 채워진 프레임이라도 일부 joint 값이 `null` 일 수 있음
- 실측 (10초 / 30fps / 145 샘플 프레임 영상):
  · 145 프레임 중 **52개만 키포인트 채워짐**, 93개는 빈 객체
  · 채워진 프레임 중에서도 일부 joint 가 `null` (예: `hind_paw: null`)

**영향**
- 프론트가 빈 프레임을 그대로 렌더링하면 스켈레톤이 깜빡이거나 사라짐
- 일부 null joint 만 가진 프레임은 부분 스켈레톤만 그려질 수 있음

**프론트 처리 옵션 (선택)**
1. 빈 프레임 / 부분 null joint 프레임을 스킵 (간격이 부자연스러울 수 있음)
2. 직전 유효 프레임의 좌표를 유지 (애니메이션 정지 효과)
3. 인접 유효 프레임 사이를 선형 보간 (가장 자연스러우나 구현 부담)

**참고**
- `min_confidence=0` 으로 요청해도 AI 측 추출 실패 프레임은 비어있음 (임계값과 무관)
- AI 가 향후 보간/dense 옵션을 제공하면 백엔드 쿼리 파라미터로 추가 검토 가능

**관련 코드**
- `app/utils/ai_client.py:fetch_keypoints` (백엔드는 변환 없이 통과)
- `app/routers/analyses.py:get_analysis_keypoints` (라우터)

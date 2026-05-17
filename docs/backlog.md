# 백로그 — 후속 작업 후보 메모

명세서 1차 구현 중 발견됐지만 현재 스코프 밖이거나, 별도 결정/협의가 필요한 항목.
신규 발견 시 위에 추가. 처리되면 해당 항목 제거 또는 "완료" 표시.

---

## BL-1 · 자체 DB 병원 seed 부족 + 카카오 매칭 휴리스틱 한계

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

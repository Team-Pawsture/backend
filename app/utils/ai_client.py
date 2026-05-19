"""
AI 분석 서버 클라이언트
- AI 서버 명세 v3: POST /api/v1/patella/analyze (동기, 평균 34초/최대 72초)
                  GET  /api/v1/patella/jobs/{jobId}
- 호출 흐름: 백엔드 라우터가 BackgroundTasks로 submit_analysis() 실행 → 결과를 DB 업데이트
- AI가 동기 호출이라 submit_analysis() 한 번으로 completed/rejected 결과를 받음.
  poll_analysis()는 사후 재조회용으로만 유지 (현재 흐름에선 거의 사용 안 함).

────────────────────────────────────────────────────────────────────────────
⚠ BackgroundTasks 한계 (analyses.py 라우터에서 함께 적용)
────────────────────────────────────────────────────────────────────────────
- FastAPI BackgroundTasks는 응답 직후 같은 워커 프로세스에서 실행됨.
  · 워커 재시작/크래시 시 진행 중인 분석은 분실 → Analysis 레코드가 queued로 영구 잔존
  · uvicorn --workers N 사용 시 어느 워커에서 실행됐는지 추적 불가
  · 동시 분석 요청은 워커 이벤트 루프 안에서 처리됨 → I/O 대기는 OK지만 무제한 누적은 위험
- 1차 배포 수준에서는 수용 (사용자 ~수십명, 동시 분석 거의 없음).
- 전환 트리거: 다음 중 하나 발생 시 Celery/RQ + Redis로 마이그레이션 권장
  · 동시 진행 분석 5건 이상 정기 발생
  · 워커 재시작 시 잔존 queued 분석 발견 빈번
  · 멀티 워커/멀티 인스턴스 배포 필요
- 잔존 queued 정리는 별도 배치(예: 1시간 이상 queued면 failed 처리)로 보완 가능.

응답 매핑 정책 (의료 정보 안전)
────────────────────────────────────────────────────────────────────────────
- 임시 추론 금지. AI가 제공하지 않는 의료 필드는 항상 null + TODO 주석.
  · predicted_stage / estimated_stage  : null (AI는 decision만 제공)
  · class_probabilities                : null (AI 3종 확률 vs 명세 5단계 — 매핑 미확정)
  · quality.score                      : null (AI 미제공)
- 응답에 노출되는 risk_level은 AI 값 그대로 통과 (high/suspicious/uncertain/low_signal).
  매핑 사전 만들지 않음 — 프론트 표시는 클라이언트에서 처리.
- confidence는 AI probabilities 중 최대값 사용 (실제 신뢰도 신호로 활용).
- recommendation.summary/action 모두 AI user_message 그대로 사용 (decision 사전 X).
- 추후 AI팀과 매핑 규칙 확정 시 _transform_ai_to_backend()의 TODO 부분만 채우면 됨.

환경변수
────────────────────────────────────────────────────────────────────────────
- AI_SERVER_URL                  : AI 서버 base URL (끝 / 없이)
- AI_MOCK_MODE                   : true면 실제 호출 없이 가짜 응답 반환
- AI_MOCK_SCENARIO               : mock 응답 종류 (completed | rejected | failed)
- AI_INTERNAL_STAGE_MAPPING      : true면 병원 추천 점수용 _internal_predicted_stage 채움
                                   (응답 노출 X, 라우터/추천 로직에서만 참조)
"""

import asyncio
import os
import uuid
from pathlib import Path

import aiohttp


# ============================================
# 환경 변수
# ============================================
AI_SERVER_URL = os.getenv("AI_SERVER_URL", "").rstrip("/")
AI_MOCK_MODE = os.getenv("AI_MOCK_MODE", "false").lower() == "true"
AI_MOCK_SCENARIO = os.getenv("AI_MOCK_SCENARIO", "completed").lower()
AI_INTERNAL_STAGE_MAPPING = os.getenv("AI_INTERNAL_STAGE_MAPPING", "false").lower() == "true"


# ============================================
# 타임아웃
# - /analyze는 평균 34초, 최대 72초 → 여유 두고 180초
# - /jobs/{jobId}는 즉시 응답 → 10초
# ============================================
AI_ANALYZE_TIMEOUT_SEC = 180
AI_POLL_TIMEOUT_SEC = 10


# ============================================
# AI decision → predicted_stage 내부 매핑 (병원 추천 점수용)
# - AI_INTERNAL_STAGE_MAPPING=true 일 때만 _internal_predicted_stage 필드에 담김
# - 응답에는 절대 노출하지 않음 (의료 정보 안전 정책)
# - 추후 AI팀과 매핑 규칙 확정되면 응답 prediction.predicted_stage 로 이전
# ============================================
_INTERNAL_STAGE_BY_DECISION = {
    "high_risk_possible": 3,
    "clinically_suspicious_possible": 2,
    "uncertain_recheck": None,
    "no_clear_high_risk_signal": None,
}


class AIServerUnavailable(Exception):
    """AI 서버 호출 실패 (네트워크 오류, 타임아웃, 미설정, 5xx 등) — 라우터에서 503으로 변환"""


# ============================================
# 1. 분석 요청 (동기 호출, 백그라운드 태스크에서 사용)
# ============================================
async def submit_analysis(video_file_path: str) -> dict:
    """
    AI 서버에 영상 분석 요청 (동기 호출, 최대 72초+ 소요).

    Returns:
        백엔드 응답 포맷 dict — _transform_ai_to_backend() 결과
        {
          "job_id": str,
          "status": "completed" | "rejected" | "failed",
          "risk_level": str | None,
          "prediction": dict | None,
          "recommendation": dict | None,
          "quality": dict | None,
          "progress": None,
          "error_message": str | None,
          ("_internal_predicted_stage": int | None  — AI_INTERNAL_STAGE_MAPPING=true 일 때만)
        }

    Raises:
        AIServerUnavailable: 환경변수 미설정, 타임아웃, 5xx, 4xx, 네트워크 오류
    """
    if AI_MOCK_MODE:
        return _mock_submit()

    if not AI_SERVER_URL:
        raise AIServerUnavailable("AI_SERVER_URL 환경변수가 설정되지 않았습니다")

    url = f"{AI_SERVER_URL}/api/v1/patella/analyze"
    filename = Path(video_file_path).name
    content_type = _guess_content_type(filename)

    try:
        timeout = aiohttp.ClientTimeout(total=AI_ANALYZE_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(video_file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("file", f, filename=filename, content_type=content_type)
                async with session.post(url, data=form) as response:
                    if response.status >= 500:
                        body_text = await _safe_text(response)
                        raise AIServerUnavailable(
                            f"AI 서버 오류 {response.status}: {body_text[:200]}"
                        )
                    if response.status >= 400:
                        # 영상 자체 문제 (확장자/길이 등). detail 추출해서 AIServerUnavailable로 던짐.
                        # 라우터에서 503 ANALYSIS503 으로 응답되며, 별도 매핑 원하면 여기서 분기 추가.
                        body = await _safe_json(response)
                        detail = body.get("detail") if isinstance(body, dict) else None
                        raise AIServerUnavailable(
                            f"AI 요청 거절 {response.status}: {detail or '알 수 없는 오류'}"
                        )
                    ai_resp = await response.json()
    except asyncio.TimeoutError:
        raise AIServerUnavailable(f"AI 호출 타임아웃 ({AI_ANALYZE_TIMEOUT_SEC}초)")
    except aiohttp.ClientError as e:
        raise AIServerUnavailable(f"AI 호출 네트워크 오류: {e}")

    return _transform_ai_to_backend(ai_resp)


# ============================================
# 2b. 관절 키포인트 조회 (P7, 2026-05-19)
# - AI: GET /api/v1/patella/jobs/{job_id}/keypoints
# - 백엔드는 그대로 프록시 (응답 변환 최소화)
# - 호출자: 라우터 GET /analyses/{analysis_id}/keypoints
# ============================================

# 백엔드 → AI 호출 시 고정 쿼리값. AI 명세서 원문 표기(camelCase) 따름.
# - AI 응답 본문은 snake_case이지만 쿼리 파라미터는 camelCase로 받음.
_KEYPOINTS_FIXED_PARAMS = {
    "coordinateType": "normalized",
    "minConfidence": 0,
    # maxFrames 미설정 (전체 프레임 반환)
}

AI_KEYPOINTS_TIMEOUT_SEC = 30


async def fetch_keypoints(job_id: str) -> dict:
    """
    AI 서버에서 job_id 의 키포인트 시계열 조회.
    응답 JSON 그대로 반환 (변환 X).

    Raises:
        AIServerUnavailable: 환경변수 미설정, 타임아웃, 4xx/5xx, 네트워크 오류
    """
    if AI_MOCK_MODE:
        return _mock_fetch_keypoints(job_id)

    if not AI_SERVER_URL:
        raise AIServerUnavailable("AI_SERVER_URL 환경변수가 설정되지 않았습니다")

    url = f"{AI_SERVER_URL}/api/v1/patella/jobs/{job_id}/keypoints"

    try:
        timeout = aiohttp.ClientTimeout(total=AI_KEYPOINTS_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=_KEYPOINTS_FIXED_PARAMS) as response:
                if response.status == 404:
                    raise AIServerUnavailable(f"AI job {job_id} 키포인트 없음")
                if response.status >= 500:
                    body_text = await _safe_text(response)
                    raise AIServerUnavailable(
                        f"AI 서버 오류 {response.status}: {body_text[:200]}"
                    )
                if response.status >= 400:
                    body = await _safe_json(response)
                    detail = body.get("detail") if isinstance(body, dict) else None
                    raise AIServerUnavailable(
                        f"AI 키포인트 거절 {response.status}: {detail or '알 수 없는 오류'}"
                    )
                return await response.json()
    except asyncio.TimeoutError:
        raise AIServerUnavailable(f"AI 키포인트 타임아웃 ({AI_KEYPOINTS_TIMEOUT_SEC}초)")
    except aiohttp.ClientError as e:
        raise AIServerUnavailable(f"AI 키포인트 네트워크 오류: {e}")


# ============================================
# 2. 분석 상태/결과 조회 (사후 재조회용)
# - 현재 흐름에서는 거의 호출되지 않음.
#   submit_analysis()가 이미 completed 결과를 반환하므로 DB 캐시로 충분.
# - AI가 향후 비동기로 바뀌거나, 외부에서 job_id로 재조회할 때 사용.
# ============================================
async def poll_analysis(job_id: str) -> dict:
    """
    AI 서버에 job 상태 조회 → 백엔드 응답 포맷 dict 반환.
    """
    if AI_MOCK_MODE:
        return _mock_poll(job_id)

    if not AI_SERVER_URL:
        raise AIServerUnavailable("AI_SERVER_URL 환경변수가 설정되지 않았습니다")

    url = f"{AI_SERVER_URL}/api/v1/patella/jobs/{job_id}"

    try:
        timeout = aiohttp.ClientTimeout(total=AI_POLL_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 404:
                    raise AIServerUnavailable(f"AI job {job_id} 없음")
                if response.status >= 500:
                    body_text = await _safe_text(response)
                    raise AIServerUnavailable(
                        f"AI 서버 오류 {response.status}: {body_text[:200]}"
                    )
                if response.status >= 400:
                    body = await _safe_json(response)
                    detail = body.get("detail") if isinstance(body, dict) else None
                    raise AIServerUnavailable(
                        f"AI 폴링 거절 {response.status}: {detail or '알 수 없는 오류'}"
                    )
                ai_resp = await response.json()
    except asyncio.TimeoutError:
        raise AIServerUnavailable(f"AI 폴링 타임아웃 ({AI_POLL_TIMEOUT_SEC}초)")
    except aiohttp.ClientError as e:
        raise AIServerUnavailable(f"AI 폴링 네트워크 오류: {e}")

    return _transform_ai_to_backend(ai_resp)


# ============================================
# 3. AI 응답 → 백엔드 응답 포맷 변환
# - 의료 정보 안전 정책: AI 미제공 필드는 항상 null + TODO
# ============================================
def _transform_ai_to_backend(ai_resp: dict) -> dict:
    status = ai_resp.get("status")
    ai_prediction = ai_resp.get("prediction") or {}
    ai_quality = ai_resp.get("quality") or {}

    # ---- prediction ----
    prediction = None
    if status == "completed":
        prediction = {
            # AI 값 그대로 통과 (high/suspicious/uncertain/low_signal)
            # TODO(AI팀 어휘 정렬): 명세서 예시는 "moderate_suspicion" 등 다른 어휘 사용 중.
            #   매핑 사전 만들지 말고, AI 어휘로 통일하든지 AI팀과 어휘 합의 필요.
            "risk_level": ai_prediction.get("risk_level"),
            # TODO(AI팀 매핑 확정): AI는 decision만 제공, stage 미제공 → null 유지
            "predicted_stage": None,
            # TODO(AI팀 매핑 확정): decision → 한글 단계 라벨 매핑 협의
            "estimated_stage": None,
            # AI probabilities 중 최대값을 confidence로 사용 (실제 신뢰도 신호)
            "confidence": _max_probability(ai_prediction.get("probabilities")),
            # TODO(AI팀 매핑 확정): AI 3종(high_risk/suspicious/abnormal) vs 명세 5단계(normal/stage1~4)
            "class_probabilities": None,
            # ── 2026-05-18 P5: 확장 필드 (AI 응답 새 키 그대로 전달) ──
            # bool 플래그는 명시적 변환 (AI가 truthy/falsy 줄 가능성 대비)
            "is_uncertain": bool(ai_prediction.get("is_uncertain")),
            "is_high_risk": bool(ai_prediction.get("is_high_risk")),
            # user_message는 prediction 안에도 노출 (기존 recommendation.summary 와 동일 소스이지만
            # 프론트 UX에서 prediction 카드 안에 표시되는 경우가 있어 중복 제공)
            "user_message": ai_prediction.get("user_message"),
            # display_metrics: AI 직접 제공값 우선, 없으면 probabilities 로 derive.
            #   포함 키: suspicious_signal_score, abnormal_signal_score,
            #            analysis_confidence_score, analysis_confidence_level
            #   AI 미제공 시 분기는 _build_display_metrics() 참고. BL-8.
            "display_metrics": _build_display_metrics(ai_prediction),
        }

    # ---- recommendation ----
    # AI user_message / safety_note 그대로 사용. decision 사전 만들지 않음.
    # summary(현상 설명)와 action(행동 권고)는 명세상 의미가 다르지만,
    # AI는 user_message 하나만 제공함 → summary에만 담고 action은 null.
    # TODO(AI팀 협의): user_message를 summary/action으로 분리하거나, AI에 별도 action 필드 요청.
    user_message = ai_prediction.get("user_message") or ai_resp.get("message")
    safety_note = ai_prediction.get("safety_note") or ai_resp.get("safety_note")
    recommendation = None
    if status == "completed":
        recommendation = {
            "summary": user_message,
            "action": None,
            "disclaimer": safety_note,
        }
    elif status == "rejected":
        issues = ai_quality.get("issues") or []
        # rejected는 issues 메시지가 곧 행동 권고(재촬영 안내)라 action에 채움.
        # summary는 상위 message 사용.
        recommendation = {
            "summary": ai_resp.get("message"),
            "action": _join_issue_messages(issues) or "영상을 다시 촬영해 주세요.",
            "disclaimer": safety_note,
        }

    # ---- quality ----
    quality = None
    if status in ("completed", "rejected"):
        issues = ai_quality.get("issues") or []
        quality = {
            "is_analyzable": ai_quality.get("is_acceptable"),
            # TODO(AI팀): score 노출 정책 협의 (현재 미제공)
            "score": None,
            "warnings": [
                i.get("message")
                for i in issues
                if i.get("severity") == "warning" and i.get("message")
            ],
        }
        if status == "rejected":
            quality["recapture_required"] = True
            quality["recapture_reasons"] = [
                i.get("message") for i in issues if i.get("message")
            ]

    out = {
        "job_id": ai_resp.get("job_id"),
        "status": status,
        # Analysis.risk_level 컬럼 저장용 (응답 prediction.risk_level과 동일 소스)
        "risk_level": ai_prediction.get("risk_level"),
        "prediction": prediction,
        "recommendation": recommendation,
        "quality": quality,
        # AI 동기 호출이라 progress 사용 케이스 없음 (running 상태 거의 발생 X)
        "progress": None,
        "error_message": ai_resp.get("error_message"),
    }

    # ---- 내부 매핑 (병원 추천 점수용, 응답 노출 금지) ----
    # 라우터에서 ai_result에 저장하기 전에 pop("_internal_predicted_stage")로 분리해
    # 별도 컬럼 또는 ai_result["_internal"] 하위에 격리 권장.
    if AI_INTERNAL_STAGE_MAPPING and status == "completed":
        decision = ai_prediction.get("decision")
        out["_internal_predicted_stage"] = _INTERNAL_STAGE_BY_DECISION.get(decision)

    return out


# ============================================
# Mock 모드 — AI 서버 없이 프론트 연동 테스트
# - AI_MOCK_SCENARIO 환경변수로 응답 시나리오 전환
# ============================================
def _mock_submit() -> dict:
    job_id = f"mock_{uuid.uuid4().hex[:12]}"

    if AI_MOCK_SCENARIO == "rejected":
        ai_resp = {
            "job_id": job_id,
            "status": "rejected",
            "quality": {
                "status": "rejected",
                "is_acceptable": False,
                "issues": [
                    {
                        "code": "too_short",
                        "severity": "reject",
                        "message": "영상이 너무 짧습니다. 강아지의 측면 보행이 4.5초 이상 보이도록 다시 촬영해 주세요.",
                    }
                ],
            },
            "prediction": None,
            "message": "영상 품질 문제로 분석을 진행할 수 없습니다.",
            "safety_note": "이 결과는 의학적 진단이 아닌 보행 기반 위험도 스크리닝입니다.",
        }
    elif AI_MOCK_SCENARIO == "failed":
        ai_resp = {
            "job_id": job_id,
            "status": "failed",
            "error_message": "AI 분석 중 오류가 발생했습니다. (mock)",
            "safety_note": "이 결과는 의학적 진단이 아닌 보행 기반 위험도 스크리닝입니다.",
        }
    else:
        # 기본: completed (clinically_suspicious_possible 시나리오)
        ai_resp = {
            "job_id": job_id,
            "status": "completed",
            "prediction": {
                "decision": "clinically_suspicious_possible",
                "risk_level": "suspicious",
                "probabilities": {
                    "prob_target_high_risk": 0.25,
                    "prob_target_suspicious": 0.45,
                    "prob_target_abnormal": 0.20,
                },
                # P5: AI 응답 확장 필드 (실제 AI가 보낼 형식 가정)
                "is_uncertain": False,
                "is_high_risk": False,
                "user_message": "보행 중 후지 움직임에 비대칭이 관찰되어 슬개골 이상 보행 가능성이 있습니다. 증상이 반복되거나 다리를 들거나 핥는 행동이 보이면 동물병원 검진을 권장합니다.",
                "display_metrics": {
                    # 필요 필드 (백엔드가 응답에 노출). AI 명세상 모두 0~100 스케일.
                    "suspicious_signal_score": 45.0,
                    "abnormal_signal_score": 20.0,
                    "analysis_confidence_score": 78.0,
                    "analysis_confidence_level": "medium",
                    # 노출 제외 필드 (filter 검증용으로 일부러 포함)
                    "score_unit": "percent",
                    "analysis_confidence_source": "probabilities_max",
                },
                "safety_note": "이 결과는 의학적 진단이 아닌 보행 기반 위험도 스크리닝입니다.",
            },
            "quality": {
                "status": "passed",
                "is_acceptable": True,
                "issues": [],
            },
            "message": "분석이 완료되었습니다. (mock)",
            "safety_note": "이 결과는 의학적 진단이 아닌 보행 기반 위험도 스크리닝입니다.",
        }

    return _transform_ai_to_backend(ai_resp)


def _mock_poll(job_id: str) -> dict:
    return _mock_submit()


# ============================================
# Mock 키포인트 — AI 서버 없이 프론트 스켈레톤 애니메이션 테스트용
# - AI 명세서 예시 구조 그대로: joints 12개, edges 11개, frames 3개
# - 응답 변환 X 라 ai_client._transform_ai_to_backend 미적용
# ============================================
_MOCK_JOINTS = [
    {"id": "ear", "label": "Ear", "model_name": "Ear"},
    {"id": "t13_spinous_process", "label": "T13 Spinous Process", "model_name": "T13 Spinous precess"},
    {"id": "dorsal_scapular_spine", "label": "Dorsal Scapular Spine", "model_name": "Dorsal scapular spine"},
    {"id": "shoulder", "label": "Shoulder", "model_name": "Acromion/Greater tubercle"},
    {"id": "elbow", "label": "Elbow", "model_name": "Lateral humeral epicondyle"},
    {"id": "wrist", "label": "Wrist", "model_name": "Ulnar styloid process"},
    {"id": "front_paw", "label": "Front Paw", "model_name": "Distal lateral aspect of fifth metacarpal bone"},
    {"id": "iliac_crest", "label": "Iliac Crest", "model_name": "Iliac crest"},
    {"id": "hip", "label": "Hip", "model_name": "Femoral greater trochanter"},
    {"id": "knee", "label": "Knee", "model_name": "Femorotibial joint"},
    {"id": "hock", "label": "Hock", "model_name": "Lateral malleolus of the distal tibia"},
    {"id": "hind_paw", "label": "Hind Paw", "model_name": "Distal lateral aspect of the fifth metatarsus"},
]

_MOCK_EDGES = [
    ["ear", "dorsal_scapular_spine"],
    ["dorsal_scapular_spine", "t13_spinous_process"],
    ["t13_spinous_process", "iliac_crest"],
    ["dorsal_scapular_spine", "shoulder"],
    ["shoulder", "elbow"],
    ["elbow", "wrist"],
    ["wrist", "front_paw"],
    ["iliac_crest", "hip"],
    ["hip", "knee"],
    ["knee", "hock"],
    ["hock", "hind_paw"],
]


def _mock_frame(frame_index: int, time_sec: float, x_shift: float) -> dict:
    """프레임 1개 생성. x_shift 로 좌→우 이동 시뮬레이션."""
    base = {
        "ear":                  (0.355 + x_shift, 0.380, 0.97),
        "t13_spinous_process":  (0.418 + x_shift, 0.343, 0.93),
        "dorsal_scapular_spine": (0.438 + x_shift, 0.395, 0.97),
        "shoulder":             (0.450 + x_shift, 0.437, 0.98),
        "elbow":                (0.460 + x_shift, 0.470, 0.98),
        "wrist":                (0.458 + x_shift, 0.525, 0.97),
        "front_paw":            (0.466 + x_shift, 0.540, 0.97),
        "iliac_crest":          (0.455 + x_shift, 0.350, 0.95),
        "hip":                  (0.466 + x_shift, 0.387, 0.94),
        "knee":                 (0.456 + x_shift, 0.462, 0.96),
        "hock":                 (0.460 + x_shift, 0.500, 0.94),
        "hind_paw":             (0.465 + x_shift, 0.518, 0.92),
    }
    return {
        "frame_index": frame_index,
        "time_sec": time_sec,
        "keypoints": {
            joint: {"x": x, "y": y, "confidence": c}
            for joint, (x, y, c) in base.items()
        },
    }


def _mock_fetch_keypoints(job_id: str) -> dict:
    """AI 키포인트 응답 mock. 3프레임 짜리 짧은 시퀀스."""
    frames = [
        _mock_frame(frame_index=0, time_sec=0.000, x_shift=0.00),
        _mock_frame(frame_index=2, time_sec=0.083, x_shift=0.01),
        _mock_frame(frame_index=4, time_sec=0.167, x_shift=0.02),
    ]
    return {
        "job_id": job_id,
        "status": "completed",
        "coordinate_type": "normalized",
        "min_confidence": 0,
        "video": {
            "width": 1280,
            "height": 720,
            "fps": 24,
            "duration_sec": 0.25,
            "total_frames": 6,
        },
        "source_segment": {
            "start_sec": 0,
            "end_sec": 0.167,
            "frame_count": 3,
            "returned_frame_count": 3,
        },
        "keypoint_summary": {
            "valid_frame_count": 3,
            "avg_confidence": 0.955,
        },
        "skeleton": {
            "joints": _MOCK_JOINTS,
            "edges": _MOCK_EDGES,
        },
        "frames": frames,
        "is_diagnostic": False,
    }


# ============================================
# 내부 헬퍼
# ============================================
def _guess_content_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
    }.get(ext, "application/octet-stream")


def _max_probability(probs):
    """AI probabilities dict → 최대값 (confidence). dict 아니거나 비어있으면 None."""
    if not isinstance(probs, dict) or not probs:
        return None
    numeric = [v for v in probs.values() if isinstance(v, (int, float))]
    return max(numeric) if numeric else None


# 2026-05-18 P5 / 2026-05-19 P8: display_metrics 빌더
# - 백엔드 응답에 노출할 4개 필드 (score_unit, analysis_confidence_source 등 AI 부가 메타는 제외)
_DISPLAY_METRICS_KEYS = (
    "suspicious_signal_score",
    "abnormal_signal_score",
    "analysis_confidence_score",
    "analysis_confidence_level",
)


def _build_display_metrics(ai_pred):
    """
    display_metrics 생성. AI 직접 제공값 우선, 없으면 probabilities 에서 derive.

    매핑 근거 (AI 모델 패키지 v3_two_stage_policy_9_5 기준):
    - suspicious_signal_score = round(prob_target_suspicious * 100, 1)
    - abnormal_signal_score   = round(prob_target_abnormal * 100, 1)
    - analysis_confidence_score: AI 모델 패키지가 아직 산출 안 함 → null
    - analysis_confidence_level: 동일 사유 → "unknown"
    추후 AI가 display_metrics 를 직접 보내기 시작하면 그 값을 우선 사용
    (백엔드 derive 는 fallback). 백로그 BL-8 참고.
    """
    if not isinstance(ai_pred, dict):
        return None

    # 1) AI 직접 제공: 4개 필드만 추림 (지금 AI 모델 패키지엔 없음, 향후 대비)
    ai_metrics = ai_pred.get("display_metrics")
    if isinstance(ai_metrics, dict):
        return {key: ai_metrics.get(key) for key in _DISPLAY_METRICS_KEYS}

    # 2) Fallback: AI probabilities 로 derive
    probs = ai_pred.get("probabilities")
    if not isinstance(probs, dict):
        return None

    susp = probs.get("prob_target_suspicious")
    abn = probs.get("prob_target_abnormal")

    return {
        "suspicious_signal_score": (
            round(susp * 100, 1) if isinstance(susp, (int, float)) else None
        ),
        "abnormal_signal_score": (
            round(abn * 100, 1) if isinstance(abn, (int, float)) else None
        ),
        "analysis_confidence_score": None,
        "analysis_confidence_level": "unknown",
    }


def _join_issue_messages(issues: list) -> str:
    msgs = [i.get("message") for i in issues if i.get("message")]
    return " ".join(msgs)


async def _safe_text(response: aiohttp.ClientResponse) -> str:
    try:
        return await response.text()
    except Exception:
        return ""


async def _safe_json(response: aiohttp.ClientResponse) -> dict:
    try:
        return await response.json()
    except Exception:
        return {}

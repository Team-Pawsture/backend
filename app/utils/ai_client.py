"""
AI 분석 서버 클라이언트 (2026-06-02 AI 2단계 분석 구조, 비동기 폴링)
- AI 서버 엔드포인트:
  · POST /api/v1/patella/jobs            (JSON, 즉시 queued 응답 → job_id 발급)
  · GET  /api/v1/patella/jobs/{job_id}   (상태/결과 폴링)
  · GET  /api/v1/patella/jobs/{job_id}/keypoints (관절 키포인트 시계열)
- 2단계 분석:
  · 1차(rear_gate, view="rear")  : 후면 영상 분석 → 측면 필요 여부 decision
  · 2차(fusion,    view="side")  : 측면 영상 fusion 분석 (parent_job_id 로 1차 연결)
- 호출 흐름:
  1) 라우터가 POST /analyses 처리 중 submit_analysis() 호출 → ai_job_id 즉시 수신
  2) 클라이언트 폴링 GET /analyses/{id} 마다 fetch_ai_job_status() 호출 → DB 업데이트
  3) status terminal 도달 후로는 DB 캐시 응답

응답 매핑 정책
────────────────────────────────────────────────────────────────────────────
- 본 클라이언트는 AI envelope 를 가공하지 않고 raw 그대로 반환한다.
  · submit_analysis()      → {"ai_job_id", "raw": <envelope>}
  · fetch_ai_job_status()  → AI envelope dict (status, analysis_stage, result, error ...)
- AI status(queued/running/succeeded/failed) → 백엔드 status 매핑, 그리고
  result(decision/risk_level/scores ...) → 화면 표시용 display_metrics / solutions 가공은
  모두 라우터(app/routers/analyses.py)에서 수행한다.

환경변수
────────────────────────────────────────────────────────────────────────────
- AI_SERVER_URL                  : AI 서버 base URL (끝 / 없이)
- AI_INTERNAL_API_KEY            : AI 서버 Bearer 토큰 (Authorization 헤더 값)
- AI_MOCK_MODE                   : true면 실제 호출 없이 가짜 응답 반환
- AI_MOCK_SCENARIO               : mock 응답 종류 (completed | fusion | failed)
"""

import asyncio
import os
import uuid
from typing import Optional

import aiohttp

from app.utils.url_helper import build_absolute_url


# ============================================
# 환경 변수
# ============================================
AI_SERVER_URL = os.getenv("AI_SERVER_URL", "").rstrip("/")
AI_INTERNAL_API_KEY = os.getenv("AI_INTERNAL_API_KEY", "")
AI_MOCK_MODE = os.getenv("AI_MOCK_MODE", "false").lower() == "true"
AI_MOCK_SCENARIO = os.getenv("AI_MOCK_SCENARIO", "completed").lower()


# ============================================
# 타임아웃
# - POST /analyses 는 즉시 queued 응답 → 30초
# - GET /jobs/{ai_job_id} 도 즉시 응답 → 60초 (네트워크 지연 대비 여유)
# ============================================
AI_SUBMIT_TIMEOUT_SEC = 30
AI_POLL_TIMEOUT_SEC = 60


class AIServerUnavailable(Exception):
    """AI 서버 호출 실패 (네트워크 오류, 타임아웃, 미설정, 5xx 등) — 라우터에서 503으로 변환"""


# ============================================
# 1. 분석 요청 (즉시 응답, 비동기 큐잉 전환)
# - 2026-06-02 AI 2단계 분석 구조: POST /api/v1/patella/jobs
#   · 1차(rear_gate): view="rear", parent_job_id 없음
#   · 2차(fusion): view="side", parent_job_id 필수 (1차 ai_job_id)
# ============================================
async def submit_analysis(
    *,
    pet_id: int,
    video_id: int,
    video_url: str,
    analysis_stage: str,  # "rear_gate" or "fusion"
    view: str,  # "rear" or "side"
    parent_job_id: Optional[str] = None,  # fusion 시 필수
) -> dict:
    """
    AI 서버에 영상 분석 요청 (POST /api/v1/patella/jobs, application/json).
    AI 가 즉시 queued 응답을 돌려주고, 실제 분석은 비동기 큐에서 수행함.

    - pet_id / video_id 는 AI 서버가 string 으로 받으므로 str() 변환 후 전송.
    - video_url 은 build_absolute_url 적용 (옵션 W: 상대경로 → R2 절대 URL).
    - parent_job_id 는 2차(fusion) 호출 시 1차(rear_gate)의 ai_job_id.

    Returns:
        {
          "ai_job_id": "<job_id 문자열>",
          "raw": <AI 응답 envelope 전체 dict>,
        }

    Raises:
        AIServerUnavailable: 환경변수 미설정, 타임아웃, 5xx, 4xx, 네트워크 오류
    """
    if AI_MOCK_MODE:
        return _mock_submit(analysis_stage=analysis_stage)

    if not AI_SERVER_URL:
        raise AIServerUnavailable("AI_SERVER_URL 환경변수가 설정되지 않았습니다")

    url = f"{AI_SERVER_URL}/api/v1/patella/jobs"

    # URL 정책 반전(2026-05-22): 라우터에서 받은 video_url 은 상대경로일 수 있음.
    # AI 서버는 HTTP GET 다운로드 필요 → 절대 URL 로 변환.
    # build_absolute_url 은 http(s):// 로 시작하면 그대로 통과(이중 prefix 방지) → 기존 DB 절대 URL row 도 안전.
    absolute_video_url = build_absolute_url(video_url)

    body = {
        "pet_id": str(pet_id),
        "video_id": str(video_id),
        "video_url": absolute_video_url,
        "view": view,
        "analysis_stage": analysis_stage,
    }
    if parent_job_id:
        body["parent_job_id"] = parent_job_id

    try:
        timeout = aiohttp.ClientTimeout(total=AI_SUBMIT_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body, headers=_auth_headers()) as response:
                if response.status >= 500:
                    body_text = await _safe_text(response)
                    raise AIServerUnavailable(
                        f"AI 서버 오류 {response.status}: {body_text[:200]}"
                    )
                if response.status >= 400:
                    # 영상 URL 형식 문제 등. detail 추출해서 AIServerUnavailable 로 던짐.
                    # 라우터에서 503 ANALYSIS503 으로 응답.
                    err_body = await _safe_json(response)
                    detail = err_body.get("detail") if isinstance(err_body, dict) else None
                    raise AIServerUnavailable(
                        f"AI 요청 거절 {response.status}: {detail or '알 수 없는 오류'}"
                    )
                ai_resp = await response.json()
    except asyncio.TimeoutError:
        raise AIServerUnavailable(f"AI 호출 타임아웃 ({AI_SUBMIT_TIMEOUT_SEC}초)")
    except aiohttp.ClientError as e:
        raise AIServerUnavailable(f"AI 호출 네트워크 오류: {e}")

    ai_job_id = ai_resp.get("job_id") if isinstance(ai_resp, dict) else None
    if not ai_job_id:
        raise AIServerUnavailable("AI 응답에 job_id 가 없습니다")

    return {"ai_job_id": ai_job_id, "raw": ai_resp}


# ============================================
# 1b. 분석 상태/결과 폴링 (GET /jobs/{ai_job_id})
# ============================================
async def fetch_ai_job_status(ai_job_id: str) -> dict:
    """
    AI 서버에서 ai_job_id 의 현재 상태/결과 envelope 조회.
    응답은 변환하지 않고 AI envelope raw 그대로 반환 — status 매핑/가공은 라우터에서 수행.

    Returns:
        AI envelope dict (status, prediction, quality, completed_at, error_message ...)

    Raises:
        AIServerUnavailable: 환경변수 미설정, 타임아웃, 5xx/4xx, 네트워크 오류
    """
    if AI_MOCK_MODE:
        return _mock_fetch_ai_job_status(ai_job_id)

    if not AI_SERVER_URL:
        raise AIServerUnavailable("AI_SERVER_URL 환경변수가 설정되지 않았습니다")

    url = f"{AI_SERVER_URL}/api/v1/patella/jobs/{ai_job_id}"

    try:
        timeout = aiohttp.ClientTimeout(total=AI_POLL_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=_auth_headers()) as response:
                if response.status == 404:
                    raise AIServerUnavailable(f"AI job {ai_job_id} 없음")
                if response.status >= 500:
                    body_text = await _safe_text(response)
                    raise AIServerUnavailable(
                        f"AI 서버 오류 {response.status}: {body_text[:200]}"
                    )
                if response.status >= 400:
                    err_body = await _safe_json(response)
                    detail = err_body.get("detail") if isinstance(err_body, dict) else None
                    raise AIServerUnavailable(
                        f"AI 폴링 거절 {response.status}: {detail or '알 수 없는 오류'}"
                    )
                return await response.json()
    except asyncio.TimeoutError:
        raise AIServerUnavailable(f"AI 폴링 타임아웃 ({AI_POLL_TIMEOUT_SEC}초)")
    except aiohttp.ClientError as e:
        raise AIServerUnavailable(f"AI 폴링 네트워크 오류: {e}")


def _auth_headers() -> dict:
    """AI 서버 Authorization 헤더. AI_INTERNAL_API_KEY 미설정 시 헤더 생략."""
    if AI_INTERNAL_API_KEY:
        return {"Authorization": f"Bearer {AI_INTERNAL_API_KEY}"}
    return {}


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
# Mock 모드 — AI 서버 없이 프론트 연동 테스트
# - AI_MOCK_SCENARIO 환경변수로 응답 시나리오 전환
# - submit: 항상 queued 즉시 응답 (실제 AI 비동기 큐잉과 동일)
# - fetch:  AI_MOCK_SCENARIO 에 따라 completed / rejected / failed envelope 반환
# ============================================
def _mock_submit(analysis_stage: str = "rear_gate") -> dict:
    """비동기 큐잉 mock — 즉시 queued envelope 반환 (2단계 구조)."""
    job_id = f"mock_{uuid.uuid4().hex[:12]}"
    raw = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "analysis_stage": analysis_stage,
        "parent_job_id": None,
        "result": None,
        "error": None,
        "message": "분석 요청이 접수되었습니다. (mock)",
    }
    return {"ai_job_id": job_id, "raw": raw}


def _mock_fetch_ai_job_status(ai_job_id: str) -> dict:
    """폴링 mock — AI_MOCK_SCENARIO 분기로 terminal envelope 반환 (2단계 구조).

    - failed: status=failed + error
    - rear_gate (기본): 1차 succeeded, decision=SIDE_UPLOAD_REQUIRED
    - fusion: 2차 succeeded, decision=SUSPECTED_ABNORMAL_GAIT
    """
    if AI_MOCK_SCENARIO == "failed":
        return {
            "job_id": ai_job_id,
            "status": "failed",
            "stage": "failed",
            "analysis_stage": "rear_gate",
            "parent_job_id": None,
            "result": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "AI 분석 중 오류가 발생했습니다. (mock)",
            },
        }

    if AI_MOCK_SCENARIO == "fusion":
        return {
            "job_id": ai_job_id,
            "status": "succeeded",
            "stage": "completed",
            "analysis_stage": "fusion",
            "parent_job_id": "mock_parent_job",
            "result": {
                "decision": "SUSPECTED_ABNORMAL_GAIT",
                "risk_level": "suspected",
                "next_action": "증상이 반복되면 동물병원 검진을 권장합니다.",
                "scores": {
                    "suspicious_signal_score": 45.0,
                    "abnormal_signal_score": 20.0,
                },
                "quality": {"is_acceptable": True, "issues": []},
                "message": "측면 융합 분석 결과 슬개골 이상 보행 가능성이 관찰되었습니다. (mock)",
                "disclaimer": "이 결과는 의학적 진단이 아닌 보행 기반 위험도 스크리닝입니다.",
            },
            "error": None,
        }

    # 기본: 1차(rear_gate) succeeded — SIDE_UPLOAD_REQUIRED 시나리오
    return {
        "job_id": ai_job_id,
        "status": "succeeded",
        "stage": "completed",
        "analysis_stage": "rear_gate",
        "parent_job_id": None,
        "result": {
            "decision": "SIDE_UPLOAD_REQUIRED",
            "risk_level": "suspected",
            "next_action": "측면 영상을 업로드하여 2차 분석을 진행해 주세요.",
            "scores": {
                "rear_abnormality_score": 55.0,
            },
            "quality": {"is_acceptable": True, "issues": []},
            "message": "후면 영상에서 이상 신호가 관찰되어 측면 영상 분석이 필요합니다. (mock)",
            "disclaimer": "이 결과는 의학적 진단이 아닌 보행 기반 위험도 스크리닝입니다.",
        },
        "error": None,
    }


# ============================================
# Mock 키포인트 — AI 서버 없이 프론트 스켈레톤 애니메이션 테스트용
# - AI 명세서 예시 구조 그대로: joints 12개, edges 11개, frames 3개
# - 응답 변환 없이 raw 그대로 프록시 (키포인트는 가공 대상 아님)
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

"""
프로젝트 전역 상수 정의
- enum 옵션 (견종, 병력, 성별)
- 2026-05-17 변경: 영문 대문자 enum 적용 (명세서 기준)
  · 견종 17종 + OTHER
  · 병력 9개 (다중 선택)
  · 성별 MALE / FEMALE
"""

# ============================================
# 견종 enum (17종 + OTHER)
# - 소형견 12종 + 중소형견 5종 + OTHER
# ============================================
DOG_BREEDS = [
    # 소형견 (12종)
    "POMERANIAN",
    "MALTESE",
    "TOY_POODLE",
    "MINIATURE_POODLE",
    "CHIHUAHUA",
    "YORKSHIRE_TERRIER",
    "SHIH_TZU",
    "BICHON_FRISE",
    "PEKINGESE",
    "MINIATURE_PINSCHER",
    "PAPILLON",
    "COCKER_SPANIEL",
    # 중소형견 (5종)
    "BOSTON_TERRIER",
    "JACK_RUSSELL_TERRIER",
    "DACHSHUND",
    "FRENCH_BULLDOG",
    "PUG",
    # 기타
    "OTHER",
]


# ============================================
# 슬개골 탈구 고위험 견종 (병원 추천 점수 가중치용)
# - 명세서 POST /hospitals/recommend 점수 기준
# ============================================
HIGH_RISK_BREEDS = {
    "POMERANIAN",
    "MALTESE",
    "CHIHUAHUA",
    "TOY_POODLE",
    "MINIATURE_POODLE",
    "YORKSHIRE_TERRIER",
    "SHIH_TZU",
    "BICHON_FRISE",
    "PEKINGESE",
    "MINIATURE_PINSCHER",
    "PAPILLON",
    "DACHSHUND",
    "PUG",
}


# ============================================
# 과거 병력 enum (9개, 다중 선택)
# - NONE 선택 시 다른 항목 동시 선택 불가
# - OTHER 선택 시 medical_history_etc 필수
# ============================================
MEDICAL_HISTORY_OPTIONS = [
    "NONE",
    "PATELLA_LUXATION_DIAGNOSED",
    "PATELLA_SURGERY",
    "HIP_DYSPLASIA",
    "CRUCIATE_LIGAMENT_INJURY",
    "DISC",
    "ARTHRITIS",
    "OBESITY",
    "OTHER",
]


# ============================================
# 성별 enum
# ============================================
GENDER_OPTIONS = [
    "MALE",
    "FEMALE",
]


# ============================================
# 알림 type enum (5종)
# - notification_helper.create_notification()에서 검증
# ============================================
NOTIFICATION_TYPES = {
    "analysis_complete",   # 분석 완료
    "high_risk_warning",   # 위험도 높음 경고
    "weekly_reminder",     # 주 1회 정기 검진 (위험도 있는 강아지)
    "monthly_reminder",    # 월 1회 정기 검진 (위험도 없는 강아지)
    "favorite_added",      # 즐겨찾기 병원 추가
}


# ============================================
# AI 2단계 분석 구조 enum (2026-06-02, 해성님 새 명세)
# - 1차(rear_gate): 후면 영상 분석 → 측면 필요 여부 결정
# - 2차(fusion): 측면 영상 fusion 분석 → 최종 결과
# ⚠️ 검증에 강제 사용하지 않음 (참고용). AI 가 응답 형식(특히 decision/risk_level
#    어휘)을 바꿀 가능성이 있어 백엔드는 string 그대로 받아 저장/노출한다.
# ============================================
from enum import Enum


class AnalysisStage(str, Enum):
    REAR_GATE = "rear_gate"
    FUSION = "fusion"


class AnalysisView(str, Enum):
    REAR = "rear"
    SIDE = "side"


class RearGateDecision(str, Enum):
    """1차(rear_gate) decision 종류"""
    INVALID_REAR_VIDEO = "INVALID_REAR_VIDEO"
    NO_OBVIOUS_REAR_ABNORMALITY = "NO_OBVIOUS_REAR_ABNORMALITY"
    SIDE_UPLOAD_RECOMMENDED = "SIDE_UPLOAD_RECOMMENDED"
    SIDE_UPLOAD_REQUIRED = "SIDE_UPLOAD_REQUIRED"


class FusionDecision(str, Enum):
    """2차(fusion) decision 종류"""
    LOW_RISK_SCREENING = "LOW_RISK_SCREENING"
    SUSPECTED_ABNORMAL_GAIT = "SUSPECTED_ABNORMAL_GAIT"
    CLINICALLY_SIGNIFICANT_SUSPECTED = "CLINICALLY_SIGNIFICANT_SUSPECTED"
    HIGH_RISK = "HIGH_RISK"
    UNCERTAIN = "UNCERTAIN"
    INVALID_SIDE_VIDEO = "INVALID_SIDE_VIDEO"


# 2차(fusion) 분석을 호출할 수 있는 1차 decision (측면 업로드 요구/권고)
SIDE_UPLOAD_DECISIONS = frozenset(
    {
        RearGateDecision.SIDE_UPLOAD_REQUIRED.value,
        RearGateDecision.SIDE_UPLOAD_RECOMMENDED.value,
    }
)


# ============================================
# P1 (2026-06-02): 프론트 화면 4영역 표시용 display_metrics 매핑
# - GET /analyses/{id} 응답 result.display_metrics 생성에 사용
# - 한글 라벨 매핑은 프론트가 수행. 백엔드는 level + 원본 decision_code 만 제공.
# ============================================
class DisplayRiskLevel(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    RECAPTURE = "recapture"
    UNCERTAIN = "uncertain"


class DisplayConfidenceLevel(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


# AI decision → 슬개골 위험도 level 매핑 (1차 rear_gate + 2차 fusion 통합)
# - dict 에 없는 decision 이 와도 에러 X → fallback (level="uncertain", decision_code 그대로)
DECISION_TO_RISK_LEVEL = {
    # 1차 (rear_gate)
    "INVALID_REAR_VIDEO": DisplayRiskLevel.RECAPTURE.value,
    "NO_OBVIOUS_REAR_ABNORMALITY": DisplayRiskLevel.LOW.value,
    "SIDE_UPLOAD_RECOMMENDED": DisplayRiskLevel.MODERATE.value,
    "SIDE_UPLOAD_REQUIRED": DisplayRiskLevel.MODERATE.value,
    # 2차 (fusion)
    "LOW_RISK_SCREENING": DisplayRiskLevel.LOW.value,
    "SUSPECTED_ABNORMAL_GAIT": DisplayRiskLevel.MODERATE.value,
    "CLINICALLY_SIGNIFICANT_SUSPECTED": DisplayRiskLevel.MODERATE.value,
    "HIGH_RISK": DisplayRiskLevel.HIGH.value,
    "UNCERTAIN": DisplayRiskLevel.UNCERTAIN.value,
    "INVALID_SIDE_VIDEO": DisplayRiskLevel.RECAPTURE.value,
}

# recapture_required.value = true 로 처리할 decision
RECAPTURE_REQUIRED_DECISIONS = frozenset(
    {"INVALID_REAR_VIDEO", "INVALID_SIDE_VIDEO", "UNCERTAIN"}
)

# recapture reason 문구 (decision 별)
RECAPTURE_REASON_BY_DECISION = {
    "INVALID_REAR_VIDEO": "영상 품질이 부족합니다. 다시 촬영해주세요.",
    "INVALID_SIDE_VIDEO": "영상 품질이 부족합니다. 다시 촬영해주세요.",
    "UNCERTAIN": "분석 신뢰도가 낮습니다. 다시 촬영해주세요.",
}


# ============================================
# P2 (2026-06-02): decision별 맞춤 솔루션 텍스트
# - GET /analyses/{id} 응답 result.solutions 생성에 사용
# - 출처: 코넬 수의대, Merck Veterinary Manual, PMC, 서비스 가이드 (예영님 자료 + 다원 매핑)
# - 매핑에 없는 decision 은 빈 배열 fallback (에러 X)
# ============================================
SOLUTIONS_BY_DECISION = {
    # 1차 (rear_gate)
    "INVALID_REAR_VIDEO": [
        "후방 또는 측면이 잘 보이도록 밝은 곳에서 강아지가 자연스럽게 걷는 모습을 5초 이상 다시 촬영해 주세요.",
        "뛰거나 줄을 당기는 상황은 피하고 평소 보행 그대로를 담아 주세요.",
        "같은 각도와 비슷한 환경에서 정기적으로 보행 영상을 촬영해 변화를 비교해 주세요.",
    ],
    "NO_OBVIOUS_REAR_ABNORMALITY": [
        "현재 영상에서는 명확한 고위험 보행 신호가 확인되지 않았습니다. 다만 본 결과는 수의학적 진단이 아니므로, 증상이 반복되거나 악화되면 수의사 상담을 권장합니다.",
        "평소 수준의 산책과 적절한 체중 관리를 유지해 주세요.",
        "미끄러운 바닥, 과도한 점프, 계단 반복 이용은 가능하면 줄여 주세요.",
        "정기적으로 보행 상태를 관찰하고, 변화가 있으면 이전 영상과 비교해 주세요.",
    ],
    "SIDE_UPLOAD_RECOMMENDED": [],
    "SIDE_UPLOAD_REQUIRED": [],
    # 2차 (fusion)
    "LOW_RISK_SCREENING": [
        "현재 영상에서는 명확한 고위험 보행 신호가 확인되지 않았습니다. 다만 본 결과는 수의학적 진단이 아니므로, 증상이 반복되거나 악화되면 수의사 상담을 권장합니다.",
        "평소 수준의 산책과 적절한 체중 관리를 유지해 주세요.",
        "미끄러운 바닥, 과도한 점프, 계단 반복 이용은 가능하면 줄여 주세요.",
        "정기적으로 보행 상태를 관찰하고, 변화가 있으면 이전 영상과 비교해 주세요.",
    ],
    "SUSPECTED_ABNORMAL_GAIT": [
        "평소 보행을 한 번 더 관찰하여 절뚝임, 뒷다리 들기, 통증 반응 등이 반복되는지 확인해 주세요. 증상이 반복되면 수의사 상담을 권장합니다.",
        "무리한 점프나 급격한 방향 전환은 가능하면 피해 주세요.",
        "적정 체중 유지가 무릎 관절 부담을 줄이는 데 도움이 됩니다.",
        "미끄럼 방지 매트를 실내에 깔고, 같은 환경에서 정기적으로 보행 영상을 촬영해 변화를 비교해 주세요.",
    ],
    "CLINICALLY_SIGNIFICANT_SUSPECTED": [
        "반복적인 절뚝임, 뒷다리 들기, 통증 반응이 보이면 수의사 상담을 권장합니다. 증상이 뚜렷하거나 악화되면 더 빨리 방문하세요.",
        "보호자가 임의로 재활 운동을 시작하기보다는, 수의사 또는 재활 전문가에게 적절한 운동 범위를 확인하세요.",
        "적정 체중 유지는 무릎 관절 부담을 줄이는 데 중요합니다.",
        "미끄럼 방지 매트를 실내에 깔고, 뛰거나 급회전하는 활동은 줄여 주세요.",
    ],
    "HIGH_RISK": [
        "가능한 빨리 수의사 진료를 예약하세요. 슬개골 탈구는 정도와 증상에 따라 보존적 관리 또는 수술적 치료가 필요할 수 있으므로, 수의사의 신체검사로 상태를 확인하는 것이 중요합니다.",
        "뛰거나 점프하는 활동은 당분간 제한하고, 짧고 천천히 걷는 산책 위주로 조절해 주세요.",
        "미끄러운 바닥에서는 활동을 줄이고, 실내에는 논슬립 매트 등을 활용해 관절 부담을 줄여 주세요.",
        "계단, 소파 오르내림처럼 무릎에 충격이 큰 동작은 가능한 줄여 주세요.",
    ],
    "UNCERTAIN": [
        "후방 또는 측면이 잘 보이도록 밝은 곳에서 강아지가 자연스럽게 걷는 모습을 5초 이상 다시 촬영해 주세요.",
        "뛰거나 줄을 당기는 상황은 피하고 평소 보행 그대로를 담아 주세요.",
        "같은 각도와 비슷한 환경에서 정기적으로 보행 영상을 촬영해 변화를 비교해 주세요.",
    ],
    "INVALID_SIDE_VIDEO": [
        "후방 또는 측면이 잘 보이도록 밝은 곳에서 강아지가 자연스럽게 걷는 모습을 5초 이상 다시 촬영해 주세요.",
        "뛰거나 줄을 당기는 상황은 피하고 평소 보행 그대로를 담아 주세요.",
        "같은 각도와 비슷한 환경에서 정기적으로 보행 영상을 촬영해 변화를 비교해 주세요.",
    ],
}

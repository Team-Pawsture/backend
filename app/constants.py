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

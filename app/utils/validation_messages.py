"""
Pydantic 검증 에러 메시지 한글화
- main.py 의 validation_exception_handler() 가 호출
- 필드별 한글 라벨 + 조사 + 에러 타입별 템플릿으로 명세서 형식 메시지 생성
- 매핑 없는 필드/타입은 None 반환 → 호출자가 Pydantic 영어 메시지로 fallback
- 라우터 내부에서 직접 raise 한 한글 메시지(예: pets.py 의 OTHER/NONE 검증)는 영향 없음

명세서 400 응답 예시 어휘를 기준으로 라벨/조사 정의.
"""

# ============================================
# 필드별 한글 라벨 + 은/는 조사
# - 명세서 표기 우선: "username은", "위도(lat)는" 등
# - 매핑 없는 필드는 fallback (영어 Pydantic 메시지)
# ============================================
FIELD_KO: dict[str, tuple[str, str]] = {
    # ----- auth -----
    "username": ("username", "은"),
    "password": ("password", "은"),
    # ----- pets -----
    "name": ("이름", "은"),
    "birth_date": ("생년월일", "은"),
    "breed": ("견종", "은"),
    "breed_etc": ("breed_etc", "는"),
    "gender": ("성별", "은"),
    "weight": ("체중", "은"),
    "medical_history": ("병력", "은"),
    "medical_history_etc": ("medical_history_etc", "는"),
    "image": ("이미지", "는"),
    # ----- analyses -----
    "pet_id": ("pet_id", "는"),
    "video": ("video", "는"),
    # ----- hospitals -----
    "lat": ("위도(lat)", "는"),
    "lng": ("경도(lng)", "는"),
    # ----- 공통 query params -----
    "limit": ("limit", "은"),
}


def translate_error(err: dict) -> str | None:
    """
    Pydantic v2 에러 dict → 한글 메시지.
    매핑 없는 필드/타입이면 None 반환 (호출자 fallback).

    err 구조 (Pydantic v2):
        {"type": "missing", "loc": (...), "msg": "...", "ctx": {...}, "input": ...}
    """
    field = str(err["loc"][-1]) if err.get("loc") else ""
    err_type = err.get("type", "")
    ctx = err.get("ctx") or {}

    label_pair = FIELD_KO.get(field)

    # value_error는 model_validator/field_validator에서 raise된 ValueError.
    # 메시지가 이미 한글일 가능성이 높으므로 필드 매핑 없어도 그대로 사용.
    if err_type == "value_error":
        msg = err.get("msg", "")
        # Pydantic v2가 "Value error, " 접두사를 붙임 → 제거
        if msg.startswith("Value error, "):
            return msg[len("Value error, "):]
        return msg or None

    if not label_pair:
        return None  # 매핑 없는 필드 → 호출자 fallback
    label, particle = label_pair

    # ---- type별 한글 템플릿 ----
    if err_type == "missing":
        return f"{label}{particle} 필수입니다"

    if err_type in ("string_too_short", "too_short"):
        min_len = ctx.get("min_length") or ctx.get("min_length_of_sequence") or ctx.get("min")
        if min_len:
            return f"{label}{particle} {min_len}자 이상이어야 합니다"
        return f"{label}{particle} 너무 짧습니다"

    if err_type in ("string_too_long", "too_long"):
        max_len = ctx.get("max_length") or ctx.get("max_length_of_sequence") or ctx.get("max")
        if max_len:
            return f"{label}{particle} {max_len}자 이하여야 합니다"
        return f"{label}{particle} 너무 깁니다"

    if err_type == "literal_error":
        # enum/Literal 위반 — 명세 어휘: "유효하지 않은 X입니다"
        # gender만 명세 예시 어휘 별도("MALE 또는 FEMALE 이어야 합니다")
        if field == "gender":
            return f"{label}{particle} MALE 또는 FEMALE 이어야 합니다"
        return f"유효하지 않은 {label}입니다"

    if err_type in ("greater_than", "gt"):
        return f"{label}{particle} 0보다 커야 합니다"

    if err_type in ("greater_than_equal", "ge"):
        ge = ctx.get("ge")
        if ge is not None:
            return f"{label}{particle} {ge} 이상이어야 합니다"
        return f"{label}{particle} 너무 작습니다"

    if err_type in ("less_than_equal", "le"):
        le = ctx.get("le")
        if le is not None:
            return f"{label}{particle} {le} 이하여야 합니다"
        return f"{label}{particle} 너무 큽니다"

    if err_type in ("int_parsing", "int_type"):
        return f"{label}{particle} 숫자(정수) 형식이어야 합니다"

    if err_type in ("float_parsing", "float_type", "decimal_parsing"):
        return f"{label}{particle} 숫자 형식이어야 합니다"

    if err_type in ("date_parsing", "date_from_datetime_parsing", "date_type"):
        return f"{label}{particle} 날짜 형식(YYYY-MM-DD)이어야 합니다"

    # 매핑 없는 타입 → fallback
    return None

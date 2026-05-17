"""
병원 추천 관련 API 라우터
- GET /hospitals : 근처 병원 리스트 (카카오 + 네이버 + 자체 DB 매칭)
- GET /hospitals/{hospital_id} : 병원 상세 (자체 DB)
- POST /hospitals/recommend : 반려견 정보 기반 추천 정렬 (2026-05-17 신규)

2026-05-17 메모:
- POST /hospitals/recommend 신규 추가
- 점수 가중치: 거리 / 영업중 / 고위험 견종 / 슬개골 기왕력

2026-05-18: predicted_stage 기반 전문분야 가중치(+40) 활성화
- 가장 최근 completed Analysis의 _internal_predicted_stage 참조
  (queued/running은 제외, AI_INTERNAL_STAGE_MAPPING=true일 때만 값 채워짐)
- 매칭 규칙: predicted_stage >= 2 AND specialty == "정형외과" → +40
- specialty 값은 자체 DB hospitals 테이블 한글 그대로 비교 (현재 seed: "정형외과", "내과", "슬개골 전문" 등)
"""

import math
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.constants import HIGH_RISK_BREEDS
from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.models.analysis import Analysis
from app.models.hospital import Hospital
from app.schemas.user import CommonResponse
from app.utils.business_hours import get_today_hours_info
from app.utils.kakao_api import search_hospitals_kakao
from app.utils.naver_api import calculate_distances_parallel
from app.utils.security import get_current_user


router = APIRouter(prefix="/hospitals", tags=["병원 추천"])


# 병원 검색 반경 (m). UI에 입력 칸이 없어 고정값 사용.
DEFAULT_SEARCH_RADIUS = 3000


# ============================================
# 헬퍼: 자체 DB와 카카오/네이버 결과 매칭
# ============================================
def _match_with_local_db(naver_hospitals: list[dict], db: Session) -> list[dict]:
    """
    외부 검색 결과 + 자체 DB hospitals 테이블 정보 합치기
    - 매칭 기준: 이름 부분 일치 + 좌표 100m 이내
    - 매칭되면 specialty, certifications, business_hours 추가
    """
    local_hospitals = db.query(Hospital).all()

    for naver_hosp in naver_hospitals:
        matched = None
        for local in local_hospitals:
            naver_name = naver_hosp["name"].replace(" ", "")
            local_name = local.name.replace(" ", "")
            name_match = naver_name in local_name or local_name in naver_name

            lat_diff = abs(naver_hosp["latitude"] - local.latitude)
            lng_diff = abs(naver_hosp["longitude"] - local.longitude)
            coord_close = lat_diff < 0.001 and lng_diff < 0.001  # 약 100m

            if name_match and coord_close:
                matched = local
                break

        if matched:
            naver_hosp["hospital_id"] = matched.hospital_id
            naver_hosp["specialty"] = matched.specialty
            naver_hosp["certifications"] = (
                matched.certifications.split(", ")
                if matched.certifications
                else []
            )
            naver_hosp["image_url"] = matched.image_url
            today_hours, is_open_now = get_today_hours_info(matched.business_hours)
            naver_hosp["today_hours"] = today_hours
            naver_hosp["is_open_now"] = is_open_now
        else:
            naver_hosp["hospital_id"] = None
            naver_hosp["specialty"] = None
            naver_hosp["certifications"] = []
            naver_hosp["image_url"] = None
            naver_hosp["today_hours"] = None
            naver_hosp["is_open_now"] = None

    return naver_hospitals


# ============================================
# GET /hospitals — 근처 병원 리스트
# ============================================
@router.get("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def get_hospitals(
    lat: float = Query(..., description="사용자 위도"),
    lng: float = Query(..., description="사용자 경도"),
    sort: str = Query("distance", description="distance(기본)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    근처 동물병원 리스트 조회
    - 카카오 로컬 검색 + 네이버 Directions + 자체 DB 매칭
    - 거리순 정렬
    """
    try:
        merged = await _build_nearby_hospitals(lat, lng, db)

        return CommonResponse(
            isSuccess=True,
            code="COMMON200",
            message="성공입니다.",
            result={"total": len(merged), "hospitals": merged},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "isSuccess": False,
                "code": "HOSPITAL503",
                "message": "병원 정보를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.",
                "result": None,
            },
        )


# ============================================
# GET /hospitals/{hospital_id} — 자체 DB 상세
# ============================================
@router.get("/{hospital_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_hospital_detail(
    hospital_id: int,
    lat: Optional[float] = Query(None, description="사용자 위도 (선택, 거리 계산용)"),
    lng: Optional[float] = Query(None, description="사용자 경도 (선택, 거리 계산용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    병원 상세 조회 (자체 DB 등록된 병원만 조회 가능)
    """
    hospital = db.query(Hospital).filter(Hospital.hospital_id == hospital_id).first()

    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "HOSPITAL404",
                "message": "해당 병원을 찾을 수 없습니다.",
                "result": None,
            },
        )

    today_hours, is_open_now = get_today_hours_info(hospital.business_hours)

    distance_meters = None
    if lat is not None and lng is not None:
        distance_meters = int(
            _haversine_distance(lat, lng, hospital.latitude, hospital.longitude)
        )

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "hospital_id": hospital.hospital_id,
            "name": hospital.name,
            "address": hospital.address,
            "phone": hospital.phone,
            "latitude": hospital.latitude,
            "longitude": hospital.longitude,
            "specialty": hospital.specialty,
            "certifications": (
                hospital.certifications.split(", ")
                if hospital.certifications
                else []
            ),
            "image_url": hospital.image_url,
            "business_hours": hospital.business_hours,
            "today_hours": today_hours,
            "is_open_now": is_open_now,
            "distance_meters": distance_meters,
        },
    )


# ============================================
# POST /hospitals/recommend — 반려견 기반 추천 정렬
# ============================================
class RecommendRequest(BaseModel):
    pet_id: int = Field(..., description="추천 대상 반려견 ID")
    lat: float = Field(..., description="사용자 위도")
    lng: float = Field(..., description="사용자 경도")


@router.post("/recommend", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def recommend_hospitals(
    payload: RecommendRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    반려견 정보 + 사용자 위치 기반 병원 추천 정렬
    - 점수 항목: 거리 / 영업중 / 고위험 견종 / 슬개골 기왕력
    - predicted_stage 기반 전문분야 가중치는 비활성 (AI 팀 답변 대기)
    - 정렬: 점수 내림차순 → 거리 오름차순 → 이름 오름차순
    """
    pet = db.query(Pet).filter(Pet.pet_id == payload.pet_id).first()
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "PET404",
                "message": "해당 반려견을 찾을 수 없습니다.",
                "result": None,
            },
        )
    if pet.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "PET403",
                "message": "접근 권한이 없습니다.",
                "result": None,
            },
        )

    try:
        nearby = await _build_nearby_hospitals(payload.lat, payload.lng, db)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "isSuccess": False,
                "code": "HOSPITAL503",
                "message": "병원 정보를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.",
                "result": None,
            },
        )

    pet_medical_history = pet.medical_history if isinstance(pet.medical_history, list) else []
    has_patella_history = any(
        item in ("PATELLA_LUXATION_DIAGNOSED", "PATELLA_SURGERY") for item in pet_medical_history
    )
    is_high_risk_breed = pet.breed in HIGH_RISK_BREEDS

    # 가장 최근 completed Analysis 의 내부 predicted_stage 조회
    # - queued/running은 제외 (status=="completed" 필터로 보장)
    # - 응답 prediction.predicted_stage는 의료 정보 안전 정책상 null이므로
    #   ai_client 의 내부 매핑 결과(_internal_predicted_stage)를 참조
    # - AI_INTERNAL_STAGE_MAPPING=false 이면 None → +40 가중치 미적용 (정상 동작)
    latest_completed = (
        db.query(Analysis)
        .filter(Analysis.pet_id == pet.pet_id, Analysis.status == "completed")
        .order_by(Analysis.created_at.desc())
        .first()
    )
    predicted_stage = None
    if latest_completed and isinstance(latest_completed.ai_result, dict):
        predicted_stage = latest_completed.ai_result.get("_internal_predicted_stage")

    scored = []
    for hosp in nearby:
        score = _compute_recommend_score(
            hosp,
            is_high_risk_breed=is_high_risk_breed,
            has_patella_history=has_patella_history,
            predicted_stage=predicted_stage,
        )
        scored.append((score, hosp))

    # 정렬: 점수 내림차순 → 거리 오름차순 → 이름 오름차순
    def sort_key(item):
        score, hosp = item
        distance = hosp.get("distance_meters")
        distance = distance if distance is not None else float("inf")
        return (-score, distance, hosp.get("name", ""))

    scored.sort(key=sort_key)
    ordered = [h for _, h in scored]

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={"total": len(ordered), "hospitals": ordered},
    )


# ============================================
# 내부: 추천 점수 계산
# - TODO(predicted_stage 활성화)는 본 함수 안에 [3/3]으로 표시. 나머지는 grep으로 추적 가능.
# ============================================
def _compute_recommend_score(
    hosp: dict,
    *,
    is_high_risk_breed: bool,
    has_patella_history: bool,
    predicted_stage: Optional[int] = None,
) -> int:
    score = 0

    # 거리: ≤200m +30 / ≤500m +20 / ≤1km +10 / 그 외 0
    distance = hosp.get("distance_meters")
    if distance is not None:
        if distance <= 200:
            score += 30
        elif distance <= 500:
            score += 20
        elif distance <= 1000:
            score += 10

    # 영업중: +10
    if hosp.get("is_open_now") == "open":
        score += 10

    # 고위험 견종: +10
    if is_high_risk_breed:
        score += 10

    # 슬개골 기왕력: +15
    if has_patella_history:
        score += 15

    # 전문분야 일치 (+40): predicted_stage >= 2 AND specialty == "정형외과"
    # - predicted_stage 는 ai_client 의 내부 매핑(_internal_predicted_stage) 값
    #   · AI_INTERNAL_STAGE_MAPPING=false 또는 completed Analysis 부재 시 None → 미적용
    # - specialty 는 자체 DB hospitals 테이블 한글 값 그대로 (seed: "정형외과"/"내과"/"슬개골 전문" 등)
    if predicted_stage is not None and predicted_stage >= 2 and hosp.get("specialty") == "정형외과":
        score += 40

    return score


# ============================================
# 공용: 카카오 + 네이버 + 자체 DB 매칭된 병원 리스트 생성
# ============================================
async def _build_nearby_hospitals(lat: float, lng: float, db: Session) -> list[dict]:
    kakao_hospitals = await search_hospitals_kakao(
        lat=lat, lng=lng, radius=DEFAULT_SEARCH_RADIUS
    )

    filtered = [
        h
        for h in kakao_hospitals
        if _haversine_distance(lat, lng, h["latitude"], h["longitude"])
        <= DEFAULT_SEARCH_RADIUS
    ]

    with_distances = await calculate_distances_parallel(lat, lng, filtered)
    merged = _match_with_local_db(with_distances, db)

    merged.sort(
        key=lambda h: h["distance_meters"] if h["distance_meters"] is not None else float("inf")
    )
    return merged


# ============================================
# 헬퍼: 직선 거리 (Haversine)
# ============================================
def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

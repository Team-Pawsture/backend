"""
병원 추천 관련 API 라우터
- GET /hospitals : 근처 병원 리스트 (네이버 API + 자체 DB 매칭)
- GET /hospitals/{hospital_id} : 병원 상세 (자체 DB 우선)
"""

import math
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.hospital import Hospital
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user
from app.utils.naver_api import calculate_distances_parallel
from app.utils.kakao_api import search_hospitals_kakao
from app.utils.business_hours import get_today_hours_info


router = APIRouter(prefix="/hospitals", tags=["병원 추천"])


# ============================================
# 헬퍼: 자체 DB와 네이버 결과 매칭
# ============================================
def _match_with_local_db(naver_hospitals: list[dict], db: Session) -> list[dict]:
    """
    네이버 검색 결과 + 자체 DB hospitals 테이블 정보 합치기
    - 매칭 기준: 이름이 비슷하고 좌표가 가까운 경우
    - 매칭되면 specialty, certifications, business_hours 등 추가
    """
    local_hospitals = db.query(Hospital).all()
    
    for naver_hosp in naver_hospitals:
        # 자체 DB에서 매칭되는 병원 찾기 (이름 부분 일치 + 좌표 100m 이내)
        matched = None
        for local in local_hospitals:
            # 이름 부분 일치
            naver_name = naver_hosp["name"].replace(" ", "")
            local_name = local.name.replace(" ", "")
            name_match = naver_name in local_name or local_name in naver_name
            
            # 좌표 거리 (대략 100m 이내)
            lat_diff = abs(naver_hosp["latitude"] - local.latitude)
            lng_diff = abs(naver_hosp["longitude"] - local.longitude)
            coord_close = lat_diff < 0.001 and lng_diff < 0.001  # 약 100m
            
            if name_match and coord_close:
                matched = local
                break
        
        # 매칭됐으면 자체 DB 정보 추가
        if matched:
            naver_hosp["hospital_id"] = matched.hospital_id
            naver_hosp["specialty"] = matched.specialty
            naver_hosp["certifications"] = (
                matched.certifications.split(", ")
                if matched.certifications else []
            )
            naver_hosp["image_url"] = matched.image_url
            today_hours, is_open_now = get_today_hours_info(matched.business_hours)
            naver_hosp["today_hours"] = today_hours
            naver_hosp["is_open_now"] = is_open_now
        else:
            # 매칭 안 됨 (네이버 정보만)
            naver_hosp["hospital_id"] = None
            naver_hosp["specialty"] = None
            naver_hosp["certifications"] = []
            naver_hosp["image_url"] = None
            naver_hosp["today_hours"] = None
            naver_hosp["is_open_now"] = None
    
    return naver_hospitals


@router.get("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def get_hospitals(
    lat: float = Query(..., description="사용자 위도"),
    lng: float = Query(..., description="사용자 경도"),
    radius: int = Query(3000, ge=100, le=10000, description="반경(m), 기본 3000"),
    sort: str = Query("distance", description="distance(기본)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    근처 동물병원 리스트 조회
    - 네이버 지역검색 + Directions API + 자체 DB 매칭
    - 거리순 정렬
    """
    try:
        # 1. 카카오 로컬 검색으로 동물병원 가져오기 (위치 기반, 최대 45개)
        kakao_hospitals = await search_hospitals_kakao(lat=lat, lng=lng, radius=radius)
        
        # 2. 반경 필터링 (카카오가 이미 반경 안만 주지만 안전망으로 한 번 더)
        filtered = [
            h for h in kakao_hospitals
            if _haversine_distance(lat, lng, h["latitude"], h["longitude"]) <= radius
        ]
        
        # 3. 실제 운전 거리 계산 (네이버 Directions API 병렬 호출)
        with_distances = await calculate_distances_parallel(lat, lng, filtered)
        
        # 4. 자체 DB와 매칭 → 큐레이션 정보 합치기
        merged = _match_with_local_db(with_distances, db)
        
        # 5. 거리순 정렬 (None은 맨 뒤로)
        merged.sort(key=lambda h: h["distance_meters"] if h["distance_meters"] is not None else float('inf'))
        
        return CommonResponse(
            isSuccess=True,
            code="COMMON200",
            message="성공입니다.",
            result={
                "total": len(merged),
                "hospitals": merged
            }
        )
    except Exception as e:
        # 네이버 API 다운, 타임아웃 등
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "isSuccess": False,
                "code": "HOSPITAL503",
                "message": "병원 정보를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.",
                "result": None
            }
        )


@router.get("/{hospital_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_hospital_detail(
    hospital_id: int,
    lat: float | None = Query(None, description="사용자 위도 (선택, 거리 계산용)"),
    lng: float | None = Query(None, description="사용자 경도 (선택, 거리 계산용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    병원 상세 조회
    - 자체 DB에 있는 hospital_id만 조회 (1차 배포 범위)
    - lat/lng 보내면 거리 계산 추가
    """
    hospital = db.query(Hospital).filter(Hospital.hospital_id == hospital_id).first()
    
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "HOSPITAL404",
                "message": "해당 병원을 찾을 수 없습니다.",
                "result": None
            }
        )
    
    # 영업시간 처리
    today_hours, is_open_now = get_today_hours_info(hospital.business_hours)
    
    # 거리 계산 (선택)
    distance_meters = None
    if lat is not None and lng is not None:
        distance_meters = int(_haversine_distance(lat, lng, hospital.latitude, hospital.longitude))
    
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
                if hospital.certifications else []
            ),
            "image_url": hospital.image_url,
            "business_hours": hospital.business_hours,
            "today_hours": today_hours,
            "is_open_now": is_open_now,
            "distance_meters": distance_meters,
        }
    )


# ============================================
# 헬퍼: 직선 거리 계산 (Haversine 공식)
# ============================================
def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    두 좌표 간 직선 거리 (미터)
    네이버 API 호출 전 1차 필터링용 (정확하진 않지만 빠름)
    """
    R = 6371000  # 지구 반지름 (미터)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c
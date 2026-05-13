"""
즐겨찾기 병원 관련 API 라우터
- POST /pets/{pet_id}/favorites/{hospital_id} : 즐겨찾기 추가
- DELETE /pets/{pet_id}/favorites/{hospital_id} : 즐겨찾기 해제
- GET /pets/{pet_id}/favorites : 즐겨찾기 목록 조회 (거리 + 영업시간 포함)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.models.hospital import Hospital
from app.models.favorite import FavoriteHospital
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user
from app.utils.notification_helper import create_notification
from app.utils.naver_api import calculate_distances_parallel
from app.utils.business_hours import get_today_hours_info


router = APIRouter(prefix="/pets", tags=["즐겨찾기"])


def _check_pet_ownership(pet_id: int, current_user: User, db: Session) -> Pet:
    """
    공통 헬퍼: 반려견이 본인 거인지 확인
    - 없으면 404, 다른 사용자 거면 403
    - 본인 반려견이면 Pet 객체 반환
    """
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()
    
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "PET404",
                "message": "해당 반려견을 찾을 수 없습니다.",
                "result": None
            }
        )
    
    if pet.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "PET403",
                "message": "접근 권한이 없습니다.",
                "result": None
            }
        )
    
    return pet


@router.post("/{pet_id}/favorites/{hospital_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def add_favorite(
    pet_id: int,
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    즐겨찾기 병원 추가
    - 권한 체크: 본인 반려견에만 추가 가능
    - 중복 체크: 이미 즐겨찾기인 병원이면 409 에러
    """
    # 1. 반려견 권한 체크
    _check_pet_ownership(pet_id, current_user, db)
    
    # 2. 병원 존재 확인
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
    
    # 3. 즐겨찾기 추가 시도
    new_favorite = FavoriteHospital(pet_id=pet_id, hospital_id=hospital_id)
    db.add(new_favorite)
    
    try:
        db.commit()
        db.refresh(new_favorite)
    except IntegrityError:
        # UniqueConstraint 위반 (이미 즐겨찾기 된 병원)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "isSuccess": False,
                "code": "FAVORITE409",
                "message": "이미 즐겨찾기에 등록된 병원입니다.",
                "result": None
            }
        )
    
    # 알림 자동 생성 (즐겨찾기 추가됨)
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()
    create_notification(
        db=db,
        user_id=current_user.user_id,
        type="favorite_added",
        title=f"{pet.name}의 즐겨찾기에 {hospital.name}을 추가했어요.",
        related_type="hospital",
        related_id=hospital.hospital_id,
    )
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="즐겨찾기에 추가되었습니다.",
        result={
            "favorite_id": new_favorite.favorite_id,
            "pet_id": new_favorite.pet_id,
            "hospital_id": new_favorite.hospital_id,
            "created_at": new_favorite.created_at.isoformat()
        }
    )


@router.delete("/{pet_id}/favorites/{hospital_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def remove_favorite(
    pet_id: int,
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    즐겨찾기 병원 해제
    - 권한 체크: 본인 반려견만 해제 가능
    - 즐겨찾기에 등록되어 있지 않으면 404 에러
    """
    # 1. 반려견 권한 체크
    _check_pet_ownership(pet_id, current_user, db)
    
    # 2. 즐겨찾기 찾기
    favorite = db.query(FavoriteHospital).filter(
        FavoriteHospital.pet_id == pet_id,
        FavoriteHospital.hospital_id == hospital_id
    ).first()
    
    if not favorite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "FAVORITE404",
                "message": "즐겨찾기에 등록되지 않은 병원입니다.",
                "result": None
            }
        )
    
    # 3. 삭제
    db.delete(favorite)
    db.commit()
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="즐겨찾기에서 제거되었습니다.",
        result={
            "pet_id": pet_id,
            "hospital_id": hospital_id,
            "deleted": True
        }
    )


@router.get("/{pet_id}/favorites", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def get_favorites(
    pet_id: int,
    lat: float | None = Query(None, description="사용자 위도 (선택, 거리 계산용)"),
    lng: float | None = Query(None, description="사용자 경도 (선택, 거리 계산용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    반려견의 즐겨찾기 병원 목록 조회
    - 권한 체크: 본인 반려견만 조회 가능
    - 등록 최신순 정렬
    - lat/lng 보내면 실제 운전 거리 계산 (네이버 Directions API)
    - 영업시간 정보 (today_hours, is_open_now) 자동 포함
    """
    # 1. 반려견 권한 체크 (Pet 객체 반환받음)
    pet = _check_pet_ownership(pet_id, current_user, db)
    
    # 2. 즐겨찾기 + 병원 정보 JOIN 조회 (최신순)
    favorites = (
        db.query(FavoriteHospital, Hospital)
        .join(Hospital, FavoriteHospital.hospital_id == Hospital.hospital_id)
        .filter(FavoriteHospital.pet_id == pet_id)
        .order_by(FavoriteHospital.created_at.desc())
        .all()
    )
    
    # 3. 기본 응답 구성 (거리/영업시간 추가 전)
    favorite_list = []
    for fav, hosp in favorites:
        # 영업시간 정보 처리
        today_hours, is_open_now = get_today_hours_info(hosp.business_hours)
        
        favorite_list.append({
            "favorite_id": fav.favorite_id,
            "hospital_id": hosp.hospital_id,
            "name": hosp.name,
            "address": hosp.address,
            "phone": hosp.phone,
            "latitude": hosp.latitude,
            "longitude": hosp.longitude,
            "image_url": hosp.image_url,
            "specialty": hosp.specialty,
            "certifications": (
                hosp.certifications.split(", ")
                if hosp.certifications else []
            ),
            "today_hours": today_hours,
            "is_open_now": is_open_now,
            "distance_meters": None,        # lat/lng 있으면 아래에서 채움
            "duration_seconds": None,
            "added_at": fav.created_at.isoformat()
        })
    
    # 4. 사용자 위치 받으면 거리 계산 (네이버 Directions 병렬 호출)
    if lat is not None and lng is not None and favorite_list:
        # 거리 계산용 데이터 추출
        hospitals_for_distance = [
            {"latitude": f["latitude"], "longitude": f["longitude"]}
            for f in favorite_list
        ]
        
        # 병렬 호출로 거리 계산
        with_distances = await calculate_distances_parallel(lat, lng, hospitals_for_distance)
        
        # 결과를 favorite_list에 합치기
        for fav, dist_info in zip(favorite_list, with_distances):
            fav["distance_meters"] = dist_info["distance_meters"]
            fav["duration_seconds"] = dist_info["duration_seconds"]
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "pet_id": pet.pet_id,
            "pet_name": pet.name,
            "total": len(favorite_list),
            "favorites": favorite_list
        }
    )
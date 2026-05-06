"""
반려견 관련 API 라우터
- POST /pets : 반려견 등록
- (예정) GET /pets
- (예정) GET /pets/{pet_id}
- (예정) PUT /pets/{pet_id}
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.schemas.pet import PetCreateRequest, PetUpdateRequest
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user


router = APIRouter(prefix="/pets", tags=["반려견"])


@router.post("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def create_pet(
    request: PetCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    반려견 등록
    - JWT 토큰에서 user_id 자동 추출
    - 한 사용자가 여러 마리 등록 가능
    """
    # DB에 저장 (user_id는 current_user에서 자동 매칭)
    new_pet = Pet(
        user_id=current_user.user_id,
        name=request.name,
        birth_year=request.birth_year,
        breed=request.breed,
        weight=request.weight,
        medical_history=request.medical_history
    )
    db.add(new_pet)
    db.commit()
    db.refresh(new_pet)
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "pet_id": new_pet.pet_id,
            "name": new_pet.name,
            "birth_year": new_pet.birth_year,
            "breed": new_pet.breed,
            "weight": new_pet.weight,
            "medical_history": new_pet.medical_history,
            "created_at": new_pet.created_at.isoformat()
        }
    )

@router.get("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_my_pets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    내 반려견 목록 조회
    - JWT 토큰의 user_id로 본인 반려견만 필터링
    - 등록된 반려견이 0마리면 빈 배열 반환
    """
    pets = db.query(Pet).filter(Pet.user_id == current_user.user_id).all()
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result=[
            {
                "pet_id": pet.pet_id,
                "name": pet.name,
                "birth_year": pet.birth_year,
                "breed": pet.breed,
                "weight": pet.weight
            }
            for pet in pets
        ]
    )


@router.get("/{pet_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_pet_detail(
    pet_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    반려견 상세 조회
    - 권한 체크: 본인 반려견만 접근 가능
    """
    # 1. 반려견 찾기
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()
    
    # 2. 없으면 404
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
    
    # 3. 본인 반려견인지 확인 → 아니면 403
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
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "pet_id": pet.pet_id,
            "name": pet.name,
            "birth_year": pet.birth_year,
            "breed": pet.breed,
            "weight": pet.weight,
            "medical_history": pet.medical_history,
            "created_at": pet.created_at.isoformat()
        }
    )


@router.put("/{pet_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def update_pet(
    pet_id: int,
    request: PetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    반려견 정보 수정
    - 권한 체크: 본인 반려견만 수정 가능
    - 부분 수정 지원 (전송된 필드만 업데이트)
    """
    # 1. 반려견 찾기
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()
    
    # 2. 없으면 404
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
    
    # 3. 본인 반려견인지 확인 → 아니면 403
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
    
    # 4. 부분 수정: 전송된 필드만 업데이트
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(pet, field, value)
    
    db.commit()
    db.refresh(pet)
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "pet_id": pet.pet_id,
            "name": pet.name,
            "birth_year": pet.birth_year,
            "breed": pet.breed,
            "weight": pet.weight,
            "medical_history": pet.medical_history,
            "created_at": pet.created_at.isoformat()
        }
    )
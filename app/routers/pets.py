"""
반려견 관련 API 라우터
- POST /pets : 반려견 등록 ✅ 구현 완료
- GET /pets : 내 반려견 목록 조회 ✅ 구현 완료
- GET /pets/{pet_id} : 반려견 상세 조회 ✅ 구현 완료
- PUT /pets/{pet_id} : 반려견 정보 수정 ✅ 구현 완료
- DELETE /pets/{pet_id} : 반려견 삭제 ✅ 구현 완료
- POST /pets/{pet_id}/image : 프로필 사진 업로드 ✅ 구현 완료
"""

from app.models.analysis import Analysis

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.schemas.pet import PetCreateRequest, PetUpdateRequest
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user
from app.utils.file_handler import (
    is_allowed_extension,
    save_pet_image,
    delete_pet_image,
)


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
    new_pet = Pet(
        user_id=current_user.user_id,
        name=request.name,
        birth_date=request.birth_date,
        breed=request.breed,
        gender=request.gender,
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
            "birth_date": new_pet.birth_date.isoformat(),
            "breed": new_pet.breed,
            "gender": new_pet.gender,
            "weight": new_pet.weight,
            "medical_history": new_pet.medical_history,
            "profile_image_url": new_pet.profile_image_url,
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
                "birth_date": pet.birth_date.isoformat(),
                "breed": pet.breed,
                "gender": pet.gender,
                "weight": pet.weight,
                "profile_image_url": pet.profile_image_url
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
    - 5/13: latest_analysis 필드 추가 (병원 추천 API 입력용)
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
    
    # ⭐ 5/13 추가: 가장 최근 분석 결과 조회 (없으면 None)
    latest = (
        db.query(Analysis)
        .filter(Analysis.pet_id == pet_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    
    latest_analysis = None
    if latest:
        # ai_result에서 안전하게 꺼내기 (옛날 구조든 새 구조든 KeyError 안 남)
        ai_result = latest.ai_result if isinstance(latest.ai_result, dict) else {}
        prediction = ai_result.get("prediction", {}) if isinstance(ai_result, dict) else {}
        recommendation = ai_result.get("recommendation", {}) if isinstance(ai_result, dict) else {}
        
        latest_analysis = {
            "analysis_id": latest.analysis_id,
            "status": latest.status,
            "risk_level": latest.risk_level,
            "predicted_stage": prediction.get("predictedStage"),
            "estimated_stage": prediction.get("estimatedStage"),
            "confidence": prediction.get("confidence"),
            "summary": recommendation.get("summary"),
            "analyzed_at": latest.created_at.isoformat() if latest.created_at else None,
        }
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "pet_id": pet.pet_id,
            "name": pet.name,
            "birth_date": pet.birth_date.isoformat(),
            "breed": pet.breed,
            "gender": pet.gender,
            "weight": pet.weight,
            "medical_history": pet.medical_history,
            "profile_image_url": pet.profile_image_url,
            "created_at": pet.created_at.isoformat(),
            "latest_analysis": latest_analysis  # ⭐ 추가
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
    
    # 부분 수정: 전송된 필드만 업데이트
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
            "birth_date": pet.birth_date.isoformat(),
            "breed": pet.breed,
            "gender": pet.gender,
            "weight": pet.weight,
            "medical_history": pet.medical_history,
            "profile_image_url": pet.profile_image_url,
            "created_at": pet.created_at.isoformat()
        }
    )

@router.delete("/{pet_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def delete_pet(
    pet_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    반려견 삭제
    - 권한 체크: 본인 반려견만 삭제 가능
    - CASCADE 삭제: 관련 analyses, favorites 같이 삭제 (DB 레벨)
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
    
    # 4. 삭제 수행
    db.delete(pet)
    db.commit()
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="반려견이 삭제되었습니다.",
        result={
            "pet_id": pet_id,
            "deleted": True
        }
    )

@router.post("/{pet_id}/image", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def upload_pet_image(
    pet_id: int,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    반려견 프로필 사진 업로드
    - multipart/form-data 형식
    - 허용 형식: jpg, jpeg, png (10MB 이하)
    - 기존 사진이 있으면 새 사진으로 교체 (이전 파일 삭제)
    """
    # 1. 반려견 찾기
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
    
    # 2. 권한 체크
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
    
    # 3. 파일 첨부 여부 체크
    if not image.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "이미지 파일을 첨부해주세요.",
                "result": None
            }
        )
    
    # 4. 파일 형식 검증 (jpg, jpeg, png만 허용)
    if not is_allowed_extension(image.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "지원하지 않는 파일 형식입니다. (jpg, jpeg, png 만 가능)",
                "result": None
            }
        )
    
    # 5. 파일 저장 (크기 검증 포함)
    try:
        new_image_url = await save_pet_image(pet_id, image)
    except ValueError as e:
        # save_pet_image에서 발생하는 에러 (크기 초과 등)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": str(e),
                "result": None
            }
        )
    
    # 6. 기존 이미지 삭제 (있으면)
    if pet.profile_image_url:
        delete_pet_image(pet.profile_image_url)
    
    # 7. DB 업데이트
    pet.profile_image_url = new_image_url
    db.commit()
    db.refresh(pet)
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="프로필 사진이 업로드되었습니다.",
        result={
            "pet_id": pet.pet_id,
            "profile_image_url": pet.profile_image_url
        }
    )
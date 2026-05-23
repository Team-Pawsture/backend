"""
반려견 관련 API 라우터
- POST /pets : 반려견 등록 (multipart/form-data)
- GET /pets : 내 반려견 목록 조회
- GET /pets/{pet_id} : 반려견 상세 조회 (latest_analysis 포함)
- PUT /pets/{pet_id} : 반려견 정보 수정 (JSON, 부분 수정)
- DELETE /pets/{pet_id} : 반려견 삭제 (CASCADE)

2026-05-17 변경:
- enum 영문 대문자 (POMERANIAN, MALE, NONE 등)
- medical_history 배열 (다중 선택)
- breed_etc / medical_history_etc 추가 (OTHER 선택 시 필수)
- weight 필수
- latest_analysis.analyzed_at → completed_at (명세 일치)
- POST /pets/{pet_id}/image 엔드포인트 제거 (명세서 외, 1차 배포 대상 아님)
"""

import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.models.analysis import Analysis
from app.schemas.pet import PetUpdateRequest, DogBreed, Gender
from app.schemas.user import CommonResponse
from app.utils import r2_client
from app.utils.security import get_current_user
from app.utils.file_handler import delete_pet_image, is_allowed_extension, save_pet_image
from app.utils.datetime_helper import to_kst_iso
# 2026-05-22 URL 정책 반전: 응답은 상대경로 그대로. build_absolute_url 사용 안 함.
from app.constants import MEDICAL_HISTORY_OPTIONS


router = APIRouter(prefix="/pets", tags=["반려견"])


# ============================================
# 헬퍼: PUT /pets/{pet_id} 부분 수정 검증
# - 전송된 필드만 검증 (None은 "변경 없음" 으로 해석)
# - 명세서 result 의 키가 정확히 "breed_etc"/"medical_history"/"medical_history_etc" 가 되도록
#   라우터에서 직접 raise (PetUpdateRequest 의 @model_validator 사용 시 loc=("body",) 가 되어
#   필드명 추적 불가 → 명세 예시와 키가 어긋남)
# ============================================
def _validate_pet_update_fields(
    breed: Optional[str],
    breed_etc: Optional[str],
    medical_history: Optional[List[str]],
    medical_history_etc: Optional[str],
) -> None:
    errors: dict[str, str] = {}

    if breed == "OTHER" and not breed_etc:
        errors["breed_etc"] = "breed가 OTHER일 때 breed_etc는 필수입니다"

    if medical_history is not None:
        if len(medical_history) == 0:
            errors["medical_history"] = "병력은 최소 1개 이상 선택해야 합니다"
        elif "NONE" in medical_history and len(medical_history) > 1:
            errors["medical_history"] = "NONE은 다른 병력 항목과 동시에 선택할 수 없습니다"
        elif "OTHER" in medical_history and not medical_history_etc:
            errors["medical_history_etc"] = "병력에 OTHER가 포함될 때 medical_history_etc는 필수입니다"

    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": errors,
            },
        )


# ============================================
# 헬퍼: medical_history form 입력 파싱 + 검증 (POST /pets 전용)
# - multipart/form-data 에서 medical_history는 JSON 문자열 또는 콤마 구분 문자열로 받음
# - 명세서 검증: 최소 1개, NONE+다른 항목 동시 불가, OTHER 포함 시 etc 필수
# ============================================
def _parse_and_validate_medical_history(
    raw: str,
    medical_history_etc: Optional[str],
) -> List[str]:
    raw_stripped = (raw or "").strip()
    parsed: List[str] = []
    if raw_stripped:
        try:
            loaded = json.loads(raw_stripped)
            if isinstance(loaded, list):
                parsed = [str(x) for x in loaded]
            else:
                parsed = [raw_stripped]
        except json.JSONDecodeError:
            parsed = [item.strip() for item in raw_stripped.split(",") if item.strip()]

    errors = {}
    if not parsed:
        errors["medical_history"] = "병력은 최소 1개 이상 선택해야 합니다"
    else:
        invalid = [v for v in parsed if v not in MEDICAL_HISTORY_OPTIONS]
        if invalid:
            errors["medical_history"] = "유효하지 않은 병력입니다"
        elif "NONE" in parsed and len(parsed) > 1:
            errors["medical_history"] = "NONE은 다른 병력 항목과 동시에 선택할 수 없습니다"
        elif "OTHER" in parsed and not medical_history_etc:
            errors["medical_history_etc"] = "병력에 OTHER가 포함될 때 medical_history_etc는 필수입니다"

    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": errors,
            },
        )

    return parsed


# ============================================
# POST /pets — 반려견 등록 (multipart/form-data)
# ============================================
@router.post("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def create_pet(
    name: str = Form(..., min_length=1, max_length=20, description="강아지 이름 (1~20자)"),
    birth_date: date = Form(..., description="생년월일 (YYYY-MM-DD)"),
    breed: DogBreed = Form(..., description="견종 (17종 + OTHER)"),
    gender: Gender = Form(..., description="성별 (MALE / FEMALE)"),
    weight: float = Form(..., gt=0, description="체중 (kg)"),
    medical_history: str = Form(
        ...,
        description='과거 병력 enum 배열. JSON ("[\\"NONE\\"]") 또는 콤마 구분 ("NONE,OBESITY") 형태',
    ),
    breed_etc: Optional[str] = Form(
        None, min_length=1, max_length=30, description="breed=OTHER일 때 직접 입력값"
    ),
    medical_history_etc: Optional[str] = Form(
        None, min_length=1, max_length=100, description="medical_history에 OTHER 포함 시 직접 입력값"
    ),
    image: Optional[UploadFile] = File(
        None, description="프로필 사진 (선택, jpg/jpeg/png, 10MB 이하)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    반려견 등록
    - JWT 토큰에서 user_id 자동 추출
    - 한 사용자가 여러 마리 등록 가능
    - 이미지는 선택. 첨부 시 함께 저장. 없으면 profile_image_url = None
    - 이미지 검증 실패 시 등록 자체 롤백 (정합성 보장)
    """
    # 0. breed=OTHER → breed_etc 필수
    if breed == "OTHER" and not breed_etc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "유효성 검사 실패",
                "result": {"breed_etc": "breed가 OTHER일 때 breed_etc는 필수입니다"},
            },
        )

    # 1. medical_history 파싱 + 검증
    medical_history_list = _parse_and_validate_medical_history(
        medical_history, medical_history_etc
    )

    # 2. 이미지 첨부 여부 판단
    has_image = image is not None and bool(image.filename)

    # 3. 이미지 첨부됐다면 확장자만 사전 검증
    if has_image and not is_allowed_extension(image.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "isSuccess": False,
                "code": "COMMON400",
                "message": "지원하지 않는 파일 형식입니다. (jpg, jpeg, png 만 가능)",
                "result": None,
            },
        )

    # 4. Pet 생성 → pet_id 확보 (이미지 저장 시 필요)
    new_pet = Pet(
        user_id=current_user.user_id,
        name=name,
        birth_date=birth_date,
        breed=breed,
        breed_etc=breed_etc if breed == "OTHER" else None,
        gender=gender,
        weight=weight,
        medical_history=medical_history_list,
        medical_history_etc=medical_history_etc if "OTHER" in medical_history_list else None,
    )
    db.add(new_pet)
    db.commit()
    db.refresh(new_pet)

    # 5. 이미지 저장 (실패 시 방금 만든 Pet 롤백)
    if has_image:
        try:
            saved_url = await save_pet_image(new_pet.pet_id, image)
        except ValueError as e:
            db.delete(new_pet)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "isSuccess": False,
                    "code": "COMMON400",
                    "message": str(e),
                    "result": None,
                },
            )
        except r2_client.R2UploadError as e:
            # R2 업로드 실패 → 방금 만든 Pet 롤백 + 503 (videos.py 와 동일 패턴, 단계 C)
            db.delete(new_pet)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "isSuccess": False,
                    "code": "STORAGE503",
                    "message": f"이미지 업로드에 실패했습니다. ({e})",
                    "result": None,
                },
            )
        new_pet.profile_image_url = saved_url
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
            "breed_etc": new_pet.breed_etc,
            "gender": new_pet.gender,
            "weight": new_pet.weight,
            "medical_history": new_pet.medical_history,
            "medical_history_etc": new_pet.medical_history_etc,
            "profile_image_url": new_pet.profile_image_url,
            "created_at": to_kst_iso(new_pet.created_at),
        },
    )


# ============================================
# GET /pets — 내 반려견 목록 조회
# ============================================
@router.get("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_my_pets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
                "profile_image_url": pet.profile_image_url,
            }
            for pet in pets
        ],
    )


# ============================================
# GET /pets/{pet_id} — 반려견 상세 (latest_analysis 포함)
# ============================================
@router.get("/{pet_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_pet_detail(
    pet_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    반려견 상세 조회
    - 권한 체크: 본인 반려견만 접근 가능
    - latest_analysis: 가장 최근 분석 1건 (진행 중이든 완료든 그대로)
    """
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()

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

    latest = (
        db.query(Analysis)
        .filter(Analysis.pet_id == pet_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )

    latest_analysis = None
    if latest:
        ai_result = latest.ai_result if isinstance(latest.ai_result, dict) else {}
        prediction = ai_result.get("prediction") if isinstance(ai_result, dict) else None
        prediction = prediction if isinstance(prediction, dict) else {}
        recommendation = ai_result.get("recommendation") if isinstance(ai_result, dict) else None
        recommendation = recommendation if isinstance(recommendation, dict) else {}

        latest_analysis = {
            "analysis_id": latest.analysis_id,
            "status": latest.status,
            # 옵션 W: DB 상대경로 그대로. build_absolute_url 호출 X.
            "video_url": latest.video_url,
            "risk_level": latest.risk_level,
            "predicted_stage": prediction.get("predicted_stage")
            or prediction.get("predictedStage"),
            "estimated_stage": prediction.get("estimated_stage")
            or prediction.get("estimatedStage"),
            "confidence": prediction.get("confidence"),
            "summary": recommendation.get("summary"),
            "completed_at": to_kst_iso(latest.completed_at),
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
            "breed_etc": pet.breed_etc,
            "gender": pet.gender,
            "weight": pet.weight,
            "medical_history": pet.medical_history,
            "medical_history_etc": pet.medical_history_etc,
            "profile_image_url": pet.profile_image_url,
            "created_at": to_kst_iso(pet.created_at),
            "latest_analysis": latest_analysis,
        },
    )


# ============================================
# PUT /pets/{pet_id} — 반려견 정보 수정 (JSON, 부분 수정)
# ============================================
@router.put("/{pet_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def update_pet(
    pet_id: int,
    request: PetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    반려견 정보 수정
    - 권한 체크: 본인 반려견만 수정 가능
    - 부분 수정 지원 (전송된 필드만 업데이트)
    - 이미지 수정은 1차 배포 대상 아님 (등록 시에만 설정 가능)
    """
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()

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

    update_data = request.model_dump(exclude_unset=True)

    # 비즈니스 검증 (NONE/OTHER 동반 규칙) — 한글 메시지로 필드명 정확히 노출
    # breed_etc 검증 시 신규 breed 또는 기존 pet.breed 둘 다 고려
    effective_breed = update_data.get("breed", pet.breed)
    _validate_pet_update_fields(
        breed=effective_breed,
        breed_etc=update_data.get("breed_etc", pet.breed_etc),
        medical_history=update_data.get("medical_history"),
        medical_history_etc=update_data.get(
            "medical_history_etc", pet.medical_history_etc
        ),
    )

    # breed가 OTHER가 아닌 값으로 바뀌면 breed_etc는 None으로 강제
    if "breed" in update_data and update_data["breed"] != "OTHER":
        update_data["breed_etc"] = None

    # medical_history가 변경되면 OTHER 포함 여부에 따라 etc 정리
    if "medical_history" in update_data:
        if "OTHER" not in update_data["medical_history"]:
            update_data["medical_history_etc"] = None

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
            "breed_etc": pet.breed_etc,
            "gender": pet.gender,
            "weight": pet.weight,
            "medical_history": pet.medical_history,
            "medical_history_etc": pet.medical_history_etc,
            "profile_image_url": pet.profile_image_url,
            "created_at": to_kst_iso(pet.created_at),
        },
    )


# ============================================
# DELETE /pets/{pet_id} — 반려견 삭제
# ============================================
@router.delete("/{pet_id}", response_model=CommonResponse, status_code=status.HTTP_200_OK)
async def delete_pet(
    pet_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    반려견 삭제
    - 권한 체크: 본인 반려견만 삭제 가능
    - CASCADE 삭제: 관련 analyses, favorites 같이 삭제 (DB 레벨)
    - 프로필 이미지가 있으면 R2 객체도 정리 (실패해도 DB 삭제는 진행 — 단계 C, 2026-05-22)
    """
    pet = db.query(Pet).filter(Pet.pet_id == pet_id).first()

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

    # R2 정리에 쓸 이미지 URL 은 DB 삭제 전에 캡처해 둠.
    image_url_to_cleanup = pet.profile_image_url

    db.delete(pet)
    db.commit()

    # R2 객체 삭제는 best-effort. 실패해도 응답은 성공으로 (delete_pet_image 자체가 예외 삼킴).
    if image_url_to_cleanup:
        await delete_pet_image(image_url_to_cleanup)

    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="반려견이 삭제되었습니다.",
        result={"pet_id": pet_id, "deleted": True},
    )

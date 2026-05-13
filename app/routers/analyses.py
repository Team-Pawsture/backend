"""
영상 분석 관련 API 라우터
- (5/12 예정) POST /analyses : 영상 분석 요청
- (5/12 예정) GET /analyses/{analysis_id} : 분석 결과 조회
- PATCH /analyses/{analysis_id}/memo : 분석 결과 메모 작성
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.pet import Pet
from app.models.analysis import Analysis
from app.schemas.analysis import AnalysisMemoRequest
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user


router = APIRouter(prefix="/analyses", tags=["영상 분석"])


@router.patch("/{analysis_id}/memo", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def update_analysis_memo(
    analysis_id: int,
    request: AnalysisMemoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    분석 결과 메모 작성/수정
    - 분석 완료 상태(status='completed')에서만 작성 가능
    - 빈 문자열로 보내면 메모 삭제 처리
    - 권한 체크: 본인 반려견의 분석만 메모 작성 가능
    """
    # 1. 분석 찾기
    analysis = db.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()
    
    # 2. 없으면 404
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS404",
                "message": "해당 분석을 찾을 수 없습니다.",
                "result": None
            }
        )
    
    # 3. 권한 체크: 분석의 pet이 본인 거인지 확인
    pet = db.query(Pet).filter(Pet.pet_id == analysis.pet_id).first()
    if not pet or pet.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS403",
                "message": "접근 권한이 없습니다.",
                "result": None
            }
        )
    
    # 4. 분석 완료 상태인지 확인
    if analysis.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "isSuccess": False,
                "code": "ANALYSIS409",
                "message": "분석이 완료된 후에 메모를 작성할 수 있습니다.",
                "result": None
            }
        )
    
    # 5. 메모 처리 (공백 trim → 빈 문자열이면 None으로 저장 = 메모 삭제)
    memo_value = request.memo.strip()
    analysis.memo = memo_value if memo_value else None
    
    db.commit()
    db.refresh(analysis)
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="메모가 저장되었습니다.",
        result={
            "analysis_id": analysis.analysis_id,
            "memo": analysis.memo,
            "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else None
        }
    )
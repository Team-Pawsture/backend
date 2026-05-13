"""
푸시 알림 구독 API 라우터
- POST /push/subscribe : 푸시 구독 등록 (중복 시 업데이트)
- DELETE /push/unsubscribe : 푸시 구독 해제
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.push_subscription import PushSubscription
from app.schemas.notification import PushSubscribeRequest, PushUnsubscribeRequest
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user


router = APIRouter(prefix="/push", tags=["푸시 알림"])


@router.post("/subscribe", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def subscribe_push(
    request: PushSubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    푸시 알림 구독 등록
    - 같은 endpoint가 이미 있으면 업데이트 (재발급된 키 반영)
    - 없으면 새로 생성
    """
    # 같은 endpoint가 이미 등록돼있는지 확인
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == request.endpoint
    ).first()
    
    if existing:
        # 업데이트: 키 갱신 + user_id 갱신 (다른 사용자가 같은 기기 쓸 수도)
        existing.user_id = current_user.user_id
        existing.p256dh_key = request.p256dh_key
        existing.auth_key = request.auth_key
        existing.user_agent = request.user_agent
        db.commit()
        db.refresh(existing)
        subscription = existing
    else:
        # 신규 등록
        subscription = PushSubscription(
            user_id=current_user.user_id,
            endpoint=request.endpoint,
            p256dh_key=request.p256dh_key,
            auth_key=request.auth_key,
            user_agent=request.user_agent,
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "subscription_id": subscription.subscription_id
        }
    )


@router.delete("/unsubscribe", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def unsubscribe_push(
    request: PushUnsubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    푸시 알림 구독 해제
    - endpoint 기준으로 삭제
    """
    subscription = db.query(PushSubscription).filter(
        PushSubscription.endpoint == request.endpoint
    ).first()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "NOTIFICATION404",
                "message": "해당 구독 정보를 찾을 수 없습니다.",
                "result": None
            }
        )
    
    db.delete(subscription)
    db.commit()
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result=None
    )
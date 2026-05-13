"""
알림 관련 API 라우터
- GET /notifications : 알림 목록 조회 (페이지네이션 + unread_count)
- PATCH /notifications/{notification_id}/read : 알림 읽음 처리
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.notification import Notification
from app.schemas.user import CommonResponse
from app.utils.security import get_current_user


router = APIRouter(prefix="/notifications", tags=["알림"])


@router.get("", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_notifications(
    limit: int = Query(20, ge=1, le=100, description="한 번에 가져올 개수 (기본 20)"),
    offset: int = Query(0, ge=0, description="시작 위치 (기본 0)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    내 알림 목록 조회 (최신순)
    - limit/offset으로 페이지네이션
    - unread_count는 전체 안 읽은 알림 개수 (페이지네이션 무관)
    """
    # 1. 안 읽은 알림 개수 (전체)
    unread_count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.user_id,
            Notification.is_read == False
        )
        .count()
    )
    
    # 2. 알림 목록 (페이지네이션)
    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    
    # 3. 응답 구성
    notification_list = [
        {
            "notification_id": n.notification_id,
            "type": n.type,
            "title": n.title,
            "is_read": n.is_read,
            "related_type": n.related_type,
            "related_id": n.related_id,
            "created_at": n.created_at.isoformat()
        }
        for n in notifications
    ]
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "unread_count": unread_count,
            "notifications": notification_list
        }
    )


@router.patch("/{notification_id}/read", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    알림 읽음 처리
    - 권한 체크: 본인 알림만 수정 가능
    """
    # 1. 알림 찾기
    notification = db.query(Notification).filter(
        Notification.notification_id == notification_id
    ).first()
    
    # 2. 없으면 404
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "isSuccess": False,
                "code": "NOTIFICATION404",
                "message": "해당 알림을 찾을 수 없습니다.",
                "result": None
            }
        )
    
    # 3. 권한 체크
    if notification.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "isSuccess": False,
                "code": "NOTIFICATION403",
                "message": "접근 권한이 없습니다.",
                "result": None
            }
        )
    
    # 4. 읽음 처리
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "notification_id": notification.notification_id,
            "is_read": notification.is_read
        }
    )
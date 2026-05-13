"""
알림 생성 공통 유틸리티
- 알림 type별로 한 함수 호출로 알림 생성
- 5/12 영상 분석 API에서도 재사용 예정
"""

from sqlalchemy.orm import Session

from app.constants import NOTIFICATION_TYPES
from app.models.notification import Notification


def create_notification(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    related_type: str | None = None,
    related_id: int | None = None,
) -> Notification:
    """
    알림 생성 + DB 저장

    사용 예시:
    create_notification(
        db=db,
        user_id=user.user_id,
        type="favorite_added",
        title=f"{pet.name}의 즐겨찾기에 {hospital.name}을 추가했어요.",
        related_type="hospital",
        related_id=hospital.hospital_id,
    )
    """
    if type not in NOTIFICATION_TYPES:
        raise ValueError(
            f"Invalid notification type: '{type}'. Allowed: {NOTIFICATION_TYPES}"
        )

    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        related_type=related_type,
        related_id=related_id,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification
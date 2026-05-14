"""
알림 생성 공통 유틸리티
- 인앱 알림 DB 저장 + (선택) 푸시 발송을 한 함수로 처리
- background_tasks 인자가 들어오면 비동기 푸시 발송 자동 트리거
  → favorite_added는 인앱만, 그 외 4종은 푸시까지 발송
"""

from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.constants import NOTIFICATION_TYPES
from app.models.notification import Notification
from app.utils.push_sender import send_push_to_user


# ============================================
# 푸시 발송 대상 type (favorite_added 제외)
# ============================================
PUSH_SEND_TYPES = {
    "analysis_complete",
    "high_risk_warning",
    "weekly_reminder",
    "monthly_reminder",
}


# ============================================
# 알림 클릭 시 이동할 URL 매핑 (related_type 기준)
# ============================================
_URL_MAP = {
    "analysis": "/analyses/{id}",
    "pet": "/pets/{id}",
    "hospital": "/hospitals/{id}",
}


def _build_push_payload(notification: Notification) -> dict:
    """
    인앱 알림 데이터를 푸시 페이로드 dict로 변환
    프론트(Service Worker)가 받는 JSON 구조
    """
    url = None
    if notification.related_type and notification.related_id is not None:
        template = _URL_MAP.get(notification.related_type)
        if template:
            url = template.format(id=notification.related_id)

    return {
        "title": notification.title,
        "body": "지금 확인해보세요.",
        "icon": "/icon-192.png",
        "data": {
            "type": notification.type,
            "notification_id": notification.notification_id,
            "related_type": notification.related_type,
            "related_id": notification.related_id,
            "url": url,
        },
    }


def create_notification(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    related_type: Optional[str] = None,
    related_id: Optional[int] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Notification:
    """
    알림 생성 + DB 저장 + (선택) 푸시 발송 예약

    사용 예시:
    create_notification(
        db=db,
        user_id=user.user_id,
        type="favorite_added",
        title=f"{pet.name}의 즐겨찾기에 {hospital.name}을 추가했어요.",
        related_type="hospital",
        related_id=hospital.hospital_id,
        background_tasks=background_tasks,  # 인자 안 넘기면 인앱만 (기존 호환)
    )

    푸시 발송 규칙:
    - background_tasks 가 None 이면 푸시 발송 안 함 (인앱만)
    - type 이 favorite_added 면 푸시 발송 안 함 (명세서 정책)
    - 그 외 4종(analysis_complete, high_risk_warning, weekly/monthly_reminder)은
      BackgroundTasks 에 send_push_to_user 등록 (응답 후 비동기 발송)
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

    if background_tasks is not None and type in PUSH_SEND_TYPES:
        payload = _build_push_payload(notification)
        background_tasks.add_task(send_push_to_user, db, user_id, payload)

    return notification

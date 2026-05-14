"""
Web Push 발송 유틸리티
- 한 사용자의 모든 push_subscriptions 디바이스에 푸시 발송
- 410/404 응답 시 만료된 구독을 자동 삭제 (clean-up)
- 5xx/타임아웃 등 일시적 에러는 로깅만, raise 안 함
- BackgroundTasks로 호출되는 것을 전제 (응답 지연 방지)
- 인앱 알림 트랜잭션과 격리: 푸시 실패는 절대 인앱 알림을 막지 않음
"""

import os
import json
import logging

from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
from sqlalchemy.orm import Session

from app.models.push_subscription import PushSubscription


load_dotenv()
logger = logging.getLogger(__name__)


# ============================================
# VAPID 환경 변수
# - PUBLIC_KEY는 프론트에서만 사용 (백엔드 발송에는 PRIVATE만 필요)
# - CLAIM_EMAIL: 푸시 서비스에 연락처를 알리는 용도 (mailto: 형식)
# ============================================
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL")


def send_push_to_user(db: Session, user_id: int, payload: dict) -> None:
    """
    user_id의 모든 구독 디바이스에 푸시 발송
    - 410/404 → 해당 구독 row 자동 삭제 (만료/구독 해제됨)
    - 그 외 에러 → 로깅만, raise 안 함
    - VAPID 환경변수가 비어 있으면 조용히 스킵 (개발 환경 호환)

    Args:
        db: SQLAlchemy 세션 (BackgroundTasks 실행 시점에도 유효한 세션)
        user_id: 발송 대상 사용자 ID
        payload: 푸시 페이로드 dict
            {
              "title": "...",
              "body": "...",
              "icon": "/icon-192.png",
              "data": {
                "type": "...",
                "notification_id": ...,
                "related_type": "...",
                "related_id": ...,
                "url": "..."
              }
            }
    """
    if not VAPID_PRIVATE_KEY or not VAPID_CLAIM_EMAIL:
        logger.warning("VAPID 환경변수 미설정 — 푸시 발송을 건너뜁니다.")
        return

    subscriptions = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == user_id)
        .all()
    )

    if not subscriptions:
        return

    payload_json = json.dumps(payload, ensure_ascii=False)
    expired_ids: list[int] = []

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {
                "p256dh": sub.p256dh_key,
                "auth": sub.auth_key,
            },
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload_json,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_CLAIM_EMAIL},
            )
        except WebPushException as ex:
            status_code = (
                ex.response.status_code if ex.response is not None else None
            )
            if status_code in (404, 410):
                expired_ids.append(sub.subscription_id)
                logger.info(
                    "푸시 구독 만료 (status=%s), 자동 삭제 예정: subscription_id=%s",
                    status_code, sub.subscription_id,
                )
            else:
                logger.warning(
                    "푸시 발송 실패 subscription_id=%s status=%s: %s",
                    sub.subscription_id, status_code, ex,
                )
        except Exception as ex:
            logger.warning(
                "푸시 발송 중 예외 subscription_id=%s: %s",
                sub.subscription_id, ex,
            )

    if expired_ids:
        try:
            db.query(PushSubscription).filter(
                PushSubscription.subscription_id.in_(expired_ids)
            ).delete(synchronize_session=False)
            db.commit()
        except Exception as ex:
            db.rollback()
            logger.warning("만료 구독 삭제 실패: %s", ex)

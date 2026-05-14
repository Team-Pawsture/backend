"""
모델 패키지 초기화
- 모든 모델을 여기서 import해야 Alembic이 인식함
"""

from app.models.user import User
from app.models.pet import Pet
from app.models.analysis import Analysis
from app.models.hospital import Hospital
from app.models.favorite import FavoriteHospital
from app.models.notification import Notification
from app.models.push_subscription import PushSubscription

__all__ = [
    "User",
    "Pet",
    "Analysis",
    "Hospital",
    "FavoriteHospital",
    "Notification",
    "PushSubscription",
]
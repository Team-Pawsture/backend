"""
모델 패키지 초기화
- 모든 모델을 여기서 import해야 Alembic이 인식함
"""

from app.models.user import User
from app.models.pet import Pet

__all__ = ["User", "Pet"]
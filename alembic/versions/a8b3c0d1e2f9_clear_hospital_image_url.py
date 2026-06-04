"""clear hospital image_url (keep specialty)

Revision ID: a8b3c0d1e2f9
Revises: f7a2b9c4d6e8
Create Date: 2026-06-04

네이버 이미지 핫링크 차단으로 프론트에서 표시 안 됨 → 병원 image_url 전체 폐기.
- upgrade: hospitals 전체 image_url = NULL (specialty 는 건드리지 않음 — 정형외과 우대 로직에서 사용 예정)
- downgrade: pass (포기한 데이터라 원복하지 않음)
- 응답 형식 불변. image_url 값만 null 로 비워짐.
"""
from alembic import op
import sqlalchemy as sa

revision = "a8b3c0d1e2f9"
down_revision = "f7a2b9c4d6e8"
branch_labels = None
depends_on = None


# 경량 테이블 정의 (모델 의존성 없이). image_url 만 사용 — specialty 미포함으로 오조작 방지.
hospitals = sa.table(
    "hospitals",
    sa.column("image_url", sa.String),
)


def upgrade():
    # hospitals 전체 image_url 을 NULL 로. specialty 는 명시적으로 포함하지 않음.
    op.execute(hospitals.update().values(image_url=None))


def downgrade():
    # 포기한 데이터 — image_url 원복하지 않음.
    pass

"""phase2: videos table + analyses.video_id FK

Revision ID: b2c3d4e5f601
Revises: a1b2c3d4e5f6
Create Date: 2026-05-22 01:00:00.000000

Phase 2 (영상 업로드 API 분리):
- videos 테이블 신설 (영상 영구 저장)
- analyses.video_id FK 추가 (nullable, 기존 row 호환)
- 기존 데이터 백필 X. 기존 analyses 는 video_id=NULL 유지.
- analyses.video_url (NOT NULL) 컬럼은 그대로. 새 INSERT 는 videos.file_url 복사값으로 채움.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f601"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. videos 테이블 생성
    op.create_table(
        "videos",
        sa.Column("video_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "pet_id",
            sa.BigInteger(),
            sa.ForeignKey("pets.pet_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            comment="소유권 검증용",
        ),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 2. analyses.video_id FK 컬럼 추가 (nullable, 기존 row 호환)
    op.add_column(
        "analyses",
        sa.Column("video_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_analyses_video_id",
        "analyses",
        "videos",
        ["video_id"],
        ["video_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_analyses_video_id", "analyses", type_="foreignkey")
    op.drop_column("analyses", "video_id")
    op.drop_table("videos")

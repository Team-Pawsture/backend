"""add ai_job_id to analyses (async polling)

Revision ID: c3d4e5f60123
Revises: b2c3d4e5f601
Create Date: 2026-05-22 10:00:00.000000

AI 서버가 동기 응답 → 비동기 큐잉으로 전환됨에 따라
POST /api/v1/patella/analyses 응답에서 받는 job_id 를 별도 컬럼에 보존.
- 기존 analyses.job_id 는 AI 응답 전체(completed 후)에 들어 있는 job_id 저장용으로 유지.
- ai_job_id 는 폴링 키 (GET /api/v1/patella/jobs/{ai_job_id}).
- 두 값이 사실상 동일하나 의미적 분리 + 폴링 단계 추적 명확화를 위해 별도 컬럼 도입.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f60123"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analyses",
        sa.Column(
            "ai_job_id",
            sa.String(length=64),
            nullable=True,
            comment="AI 비동기 폴링용 job ID (POST /analyses 응답에서 즉시 수신)",
        ),
    )
    op.create_index(
        "ix_analyses_ai_job_id",
        "analyses",
        ["ai_job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_ai_job_id", table_name="analyses")
    op.drop_column("analyses", "ai_job_id")

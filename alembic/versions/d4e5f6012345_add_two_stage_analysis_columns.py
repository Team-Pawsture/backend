"""add two stage analysis columns

Revision ID: d4e5f6012345
Revises: c3d4e5f60123
Create Date: 2026-06-02 09:00:00.000000

AI 서버가 1차(rear_gate)/2차(fusion) 2단계 분석 구조로 전환됨에 따라
analyses 테이블에 단계 구분 컬럼 3개 추가.
- analysis_stage : rear_gate / fusion (NOT NULL, 기존 row 는 server_default 'rear_gate')
- view           : rear / side       (NOT NULL, 기존 row 는 server_default 'rear')
- parent_analysis_id : 2차 fusion 이 가리키는 1차 rear_gate analysis_id (self FK, NULL 허용)

기존 컬럼(ai_job_id, video_url, status, risk_level, ai_result, error_message 등) 변경 없음.
AI 응답 구조가 바뀌었지만 ai_result(JSON)에 새 응답 envelope 를 통째 저장하여 호환.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6012345"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f60123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analyses",
        sa.Column(
            "analysis_stage",
            sa.String(length=20),
            nullable=False,
            server_default="rear_gate",
            comment="rear_gate(1차) / fusion(2차)",
        ),
    )
    op.add_column(
        "analyses",
        sa.Column(
            "view",
            sa.String(length=10),
            nullable=False,
            server_default="rear",
            comment="rear(후면, 1차) / side(측면, 2차)",
        ),
    )
    op.add_column(
        "analyses",
        sa.Column(
            "parent_analysis_id",
            sa.BigInteger(),
            nullable=True,
            comment="2차 fusion 이 가리키는 1차 rear_gate 분석 ID",
        ),
    )
    op.create_foreign_key(
        "fk_analyses_parent_analysis_id",
        "analyses",
        "analyses",
        ["parent_analysis_id"],
        ["analysis_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_analyses_parent_analysis_id", "analyses", type_="foreignkey"
    )
    op.drop_column("analyses", "parent_analysis_id")
    op.drop_column("analyses", "view")
    op.drop_column("analyses", "analysis_stage")

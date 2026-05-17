"""unique partial index to block duplicate in-progress analyses per pet

Revision ID: a1b2c3d4e5f6
Revises: 323e63da47fc
Create Date: 2026-05-18 00:30:00.000000

목적:
- POST /analyses 의 중복 요청 차단(409 ANALYSIS409)을 DB 레벨에서 보장.
- 기존 라우터의 SELECT 기반 in_progress 체크는 동시 요청 race에서 우회됨.
- 부분 유니크 인덱스로 INSERT 시점에 IntegrityError 발생 → 라우터에서 409로 변환.

영향:
- status가 queued / running 인 행만 인덱스에 포함됨 (partial WHERE 조건).
- completed / rejected / failed 행은 무제한 생성 가능 (조건에서 제외).
- 기존 데이터: 인덱스 생성 전에 동일 pet에 queued/running이 2건 이상이면 실패.
  Test 2 race로 생긴 행들은 모두 completed로 끝났으므로 충돌 없음 (확인 완료).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '323e63da47fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "uq_analyses_pet_in_progress"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDEX_NAME}
        ON analyses (pet_id)
        WHERE status IN ('queued', 'running')
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

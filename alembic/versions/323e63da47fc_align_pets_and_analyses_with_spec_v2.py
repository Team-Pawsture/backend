"""align pets and analyses with spec v2 (enums uppercase, etc fields, analysis status)

Revision ID: 323e63da47fc
Revises: 32c4246ca6db
Create Date: 2026-05-17 00:00:00.000000

명세서 v2 정합성 마이그레이션
- pets:
  · breed: 한글 enum → 영문 대문자 enum (17종 + OTHER), PUG 추가
  · gender: male/female → MALE/FEMALE
  · medical_history: 단일 문자열 → JSON 배열 (다중 선택)
  · breed_etc, medical_history_etc 컬럼 추가 (OTHER 선택 시 입력값)
  · weight: nullable=True → nullable=False
- analyses:
  · status: pending/processing → queued/running 매핑
  · job_id 컬럼 추가 (AI 서버 job 추적)
  · completed_at 컬럼 추가 (분석 종료 시각)
  · memo 컬럼 제거 (1차 배포 대상 아님)
  · updated_at 컬럼은 유지 (status 전환 추적용, API 응답에는 비노출)

⚠️ 백워드 호환 데이터 매핑:
  · 알 수 없는 견종 → OTHER + breed_etc="(원본)"
  · 알 수 없는 병력 → ["NONE"]
  · weight NULL → 5.0 (소형견 중앙값)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '323e63da47fc'
down_revision: Union[str, Sequence[str], None] = '32c4246ca6db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ============================================
# 매핑 테이블
# ============================================
BREED_MAP = {
    "포메라니안": "POMERANIAN",
    "말티즈": "MALTESE",
    "토이푸들": "TOY_POODLE",
    "미니어처푸들": "MINIATURE_POODLE",
    "치와와": "CHIHUAHUA",
    "요크셔테리어": "YORKSHIRE_TERRIER",
    "시츄": "SHIH_TZU",
    "비숑프리제": "BICHON_FRISE",
    "페키니즈": "PEKINGESE",
    "미니핀": "MINIATURE_PINSCHER",
    "빠삐용": "PAPILLON",
    "코카스파니엘": "COCKER_SPANIEL",
    "보스턴테리어": "BOSTON_TERRIER",
    "잭러셀테리어": "JACK_RUSSELL_TERRIER",
    "닥스훈트": "DACHSHUND",
    "프렌치불독": "FRENCH_BULLDOG",
    "기타": "OTHER",
}

MEDICAL_MAP = {
    "없음": "NONE",
    "슬개골 탈구 이력 있음": "PATELLA_LUXATION_DIAGNOSED",
    "슬개골 수술 경험 있음": "PATELLA_SURGERY",
    "관절 질환 (슬개골 외)": "ARTHRITIS",
    "근육/인대 부상 이력": "CRUCIATE_LIGAMENT_INJURY",
    "기타": "OTHER",
}


def upgrade() -> None:
    # ===================================================================
    # pets 테이블
    # ===================================================================

    # 1) breed_etc, medical_history_etc 컬럼 추가
    op.add_column('pets', sa.Column('breed_etc', sa.String(length=30), nullable=True,
                                    comment='견종이 OTHER일 때 직접 입력값 (1~30자)'))
    op.add_column('pets', sa.Column('medical_history_etc', sa.String(length=100), nullable=True,
                                    comment='병력에 OTHER 포함 시 직접 입력값 (1~100자)'))

    # 2) 견종 한글 → 영문 매핑. 알 수 없는 값은 OTHER + 원본을 breed_etc에 보존.
    for ko, en in BREED_MAP.items():
        op.execute(sa.text("UPDATE pets SET breed = :en WHERE breed = :ko")
                   .bindparams(en=en, ko=ko))

    # 매핑 안 된 견종 → OTHER + breed_etc에 원본 보존 (TRIM 100자 컷)
    op.execute(sa.text("""
        UPDATE pets
        SET breed_etc = LEFT(breed, 30),
            breed = 'OTHER'
        WHERE breed NOT IN (
          'POMERANIAN','MALTESE','TOY_POODLE','MINIATURE_POODLE','CHIHUAHUA',
          'YORKSHIRE_TERRIER','SHIH_TZU','BICHON_FRISE','PEKINGESE',
          'MINIATURE_PINSCHER','PAPILLON','COCKER_SPANIEL',
          'BOSTON_TERRIER','JACK_RUSSELL_TERRIER','DACHSHUND','FRENCH_BULLDOG','PUG',
          'OTHER'
        )
    """))

    # 3) gender: male/female → MALE/FEMALE
    op.execute("UPDATE pets SET gender = 'MALE' WHERE gender ILIKE 'male'")
    op.execute("UPDATE pets SET gender = 'FEMALE' WHERE gender ILIKE 'female'")
    op.execute("UPDATE pets SET gender = 'MALE' WHERE gender NOT IN ('MALE','FEMALE')")

    # 4) medical_history: 임시 JSON 컬럼 생성 → 매핑 → 원본 삭제 → rename
    op.add_column('pets', sa.Column('medical_history_new', sa.JSON(), nullable=True))

    for ko, en in MEDICAL_MAP.items():
        op.execute(sa.text(
            "UPDATE pets SET medical_history_new = CAST(:json AS json) WHERE medical_history = :ko"
        ).bindparams(json=f'["{en}"]', ko=ko))

    # 매핑 안 된 값은 ["NONE"]
    op.execute("""
        UPDATE pets
        SET medical_history_new = '["NONE"]'::json
        WHERE medical_history_new IS NULL
    """)

    op.drop_column('pets', 'medical_history')
    op.alter_column('pets', 'medical_history_new',
                    new_column_name='medical_history',
                    existing_type=sa.JSON(),
                    nullable=False,
                    existing_comment=None,
                    comment='과거 병력 enum 배열 (9개 옵션 중 다중 선택)')

    # 5) weight NULL 백필 + NOT NULL 적용
    op.execute("UPDATE pets SET weight = 5.0 WHERE weight IS NULL")
    op.alter_column('pets', 'weight',
                    existing_type=sa.Float(),
                    nullable=False,
                    comment='체중 kg')

    # 6) breed 컬럼 comment 갱신
    op.alter_column('pets', 'breed',
                    existing_type=sa.String(length=50),
                    existing_nullable=False,
                    comment='견종 (17종 + OTHER enum, 영문 대문자)',
                    existing_comment='견종 (16종 + 기타 enum)')
    op.alter_column('pets', 'gender',
                    existing_type=sa.String(length=10),
                    existing_nullable=False,
                    comment='성별 (MALE/FEMALE)',
                    existing_comment='성별 (male/female)')

    # ===================================================================
    # analyses 테이블
    # ===================================================================

    # 1) status 값 매핑 (pending → queued, processing → running)
    op.execute("UPDATE analyses SET status = 'queued' WHERE status = 'pending'")
    op.execute("UPDATE analyses SET status = 'running' WHERE status = 'processing'")
    op.execute("""
        UPDATE analyses
        SET status = 'queued'
        WHERE status NOT IN ('queued','running','completed','rejected','failed')
    """)

    op.alter_column('analyses', 'status',
                    existing_type=sa.String(length=20),
                    existing_nullable=False,
                    comment='queued/running/completed/rejected/failed',
                    existing_comment='pending/processing/completed/failed')

    # 2) job_id, completed_at 컬럼 추가
    op.add_column('analyses', sa.Column('job_id', sa.String(length=100), nullable=True,
                                        comment='AI 서버에서 발급한 job ID'))
    op.add_column('analyses', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True,
                                        comment='분석 종료 시각 (completed/rejected/failed)'))

    # 3) memo 컬럼만 제거 (1차 배포 대상 아님). updated_at은 status 추적용으로 유지.
    op.drop_column('analyses', 'memo')

    # 4) risk_level 길이 확장 (기존 20 → 50, 명세 라벨 길이 대비)
    op.alter_column('analyses', 'risk_level',
                    existing_type=sa.String(length=20),
                    type_=sa.String(length=50),
                    existing_nullable=True,
                    comment='AI 위험도 라벨 (예: moderate_suspicion)',
                    existing_comment='normal/caution/danger')


def downgrade() -> None:
    # ===================================================================
    # analyses 테이블 원복
    # ===================================================================
    op.alter_column('analyses', 'risk_level',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=20),
                    existing_nullable=True,
                    comment='normal/caution/danger',
                    existing_comment='AI 위험도 라벨 (예: moderate_suspicion)')

    op.add_column('analyses', sa.Column('memo', sa.String(length=200), nullable=True,
                                        comment='사용자 메모 (0~200자, nullable)'))

    op.drop_column('analyses', 'completed_at')
    op.drop_column('analyses', 'job_id')

    op.execute("UPDATE analyses SET status = 'pending' WHERE status = 'queued'")
    op.execute("UPDATE analyses SET status = 'processing' WHERE status = 'running'")
    op.execute("UPDATE analyses SET status = 'failed' WHERE status = 'rejected'")

    op.alter_column('analyses', 'status',
                    existing_type=sa.String(length=20),
                    existing_nullable=False,
                    comment='pending/processing/completed/failed',
                    existing_comment='queued/running/completed/rejected/failed')

    # ===================================================================
    # pets 테이블 원복
    # ===================================================================
    op.alter_column('pets', 'gender',
                    existing_type=sa.String(length=10),
                    existing_nullable=False,
                    comment='성별 (male/female)',
                    existing_comment='성별 (MALE/FEMALE)')
    op.alter_column('pets', 'breed',
                    existing_type=sa.String(length=50),
                    existing_nullable=False,
                    comment='견종 (16종 + 기타 enum)',
                    existing_comment='견종 (17종 + OTHER enum, 영문 대문자)')

    op.alter_column('pets', 'weight',
                    existing_type=sa.Float(),
                    nullable=True,
                    comment='체중 kg (선택)',
                    existing_comment='체중 kg')

    # medical_history: JSON 배열 → 단일 문자열
    op.add_column('pets', sa.Column('medical_history_old', sa.String(length=50), nullable=True))
    op.execute("""
        UPDATE pets
        SET medical_history_old = COALESCE(
          (medical_history::jsonb ->> 0),
          '없음'
        )
    """)
    op.drop_column('pets', 'medical_history')
    op.alter_column('pets', 'medical_history_old',
                    new_column_name='medical_history',
                    existing_type=sa.String(length=50),
                    nullable=False,
                    comment='과거 병력 (6개 enum)')

    op.execute("UPDATE pets SET gender = 'male' WHERE gender = 'MALE'")
    op.execute("UPDATE pets SET gender = 'female' WHERE gender = 'FEMALE'")

    # breed 영문 → 한글 (베스트 에포트)
    reverse_breed = {v: k for k, v in BREED_MAP.items()}
    for en, ko in reverse_breed.items():
        op.execute(sa.text("UPDATE pets SET breed = :ko WHERE breed = :en")
                   .bindparams(ko=ko, en=en))

    op.drop_column('pets', 'medical_history_etc')
    op.drop_column('pets', 'breed_etc')

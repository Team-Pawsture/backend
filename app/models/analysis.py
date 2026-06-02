"""
Analysis 모델 (영상 분석 테이블)
- 2026-05-17 변경: 명세서 v2 반영
  · status 값: queued / running / completed / rejected / failed
  · job_id 컬럼 추가 (AI 서버 job 추적)
  · completed_at 컬럼 추가 (분석 종료 시각)
  · memo 컬럼 제거 (1차 배포 대상 아님)
- 2026-05-22 변경: AI 서버 비동기 큐잉 전환
  · ai_job_id 컬럼 추가 (POST /api/v1/patella/analyses 응답 직후 저장,
    이후 GET /api/v1/patella/jobs/{ai_job_id} 폴링 키)
- 2026-06-02 변경: AI 2단계 분석 구조 도입 (해성님 새 명세)
  · analysis_stage 컬럼 추가 (rear_gate / fusion)
  · view 컬럼 추가 (rear / side)
  · parent_analysis_id 컬럼 추가 (2차 fusion 이 1차 rear_gate 를 가리키는 self FK)
  · AI 엔드포인트 /api/v1/patella/analyses → /jobs 로 변경. ai_result 에 새 응답 envelope 통째 저장.
"""

from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func

from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    analysis_id = Column(BigInteger, primary_key=True, autoincrement=True)
    pet_id = Column(BigInteger, ForeignKey("pets.pet_id", ondelete="CASCADE"), nullable=False)
    video_url = Column(String(500), nullable=False, comment="업로드된 영상 URL (Phase 2부터는 videos.file_url 복사값)")
    # Phase 2 (2026-05-22): videos 테이블 분리 후 FK 도입. 기존 row 호환 위해 nullable.
    # 새 INSERT 는 항상 채워짐. 기존 row(id <= phase2 적용 직전 max)는 NULL.
    video_id = Column(BigInteger, ForeignKey("videos.video_id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(100), nullable=True, comment="AI 서버에서 발급한 job ID")
    ai_job_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="AI 비동기 폴링용 job ID (POST /analyses 응답에서 즉시 수신)",
    )
    # 2026-06-02 AI 2단계 분석 구조
    analysis_stage = Column(
        String(20),
        nullable=False,
        server_default="rear_gate",
        comment="rear_gate(1차) / fusion(2차)",
    )
    view = Column(
        String(10),
        nullable=False,
        server_default="rear",
        comment="rear(후면, 1차) / side(측면, 2차)",
    )
    parent_analysis_id = Column(
        BigInteger,
        ForeignKey("analyses.analysis_id", ondelete="SET NULL"),
        nullable=True,
        comment="2차 fusion 이 가리키는 1차 rear_gate 분석 ID",
    )
    status = Column(
        String(20),
        nullable=False,
        default="queued",
        comment="queued/running/completed/rejected/failed",
    )
    risk_level = Column(String(50), nullable=True, comment="AI 위험도 라벨 (예: moderate_suspicion)")
    ai_result = Column(JSON, nullable=True, comment="AI 응답 전체 (prediction, recommendation, quality)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="레코드 갱신 시각 (status 전환 추적용, API 응답에는 비노출)",
    )
    completed_at = Column(DateTime(timezone=True), nullable=True, comment="분석 종료 시각 (completed/rejected/failed)")

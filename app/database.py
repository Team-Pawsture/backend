"""
DB 연결 설정
- .env 파일에서 DATABASE_URL 읽어와서 PostgreSQL 연결
- SQLAlchemy 엔진 + 세션 생성
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# .env 파일 읽기
load_dotenv()

# 환경 변수에서 DB 주소 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL이 .env에 설정되지 않았습니다!")

# SQLAlchemy 엔진 생성 (DB 연결 통로)
engine = create_engine(DATABASE_URL)

# 세션 팩토리 (각 요청마다 새 세션을 만들 때 사용)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 모델이 상속할 부모 클래스
Base = declarative_base()


# FastAPI 의존성 주입용 함수 (나중에 API에서 사용)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
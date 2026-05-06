"""
FastAPI 애플리케이션 진입점
- 모든 라우터를 여기서 등록
- CORS 설정
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, pets


app = FastAPI(
    title="성신에이전시 백엔드 API",
    description="반려견 슬개골 탈구 방지 걸음 분석 서비스",
    version="0.1.0"
)


# CORS 설정 (프론트엔드와 통신할 수 있도록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 단계는 전체 허용, 배포 시 도메인 제한 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 라우터 등록
app.include_router(auth.router)
app.include_router(pets.router)


@app.get("/")
def root():
    """헬스 체크 — 서버 살아있는지 확인용"""
    return {"message": "성신에이전시 백엔드 서버 작동 중! 🔥"}
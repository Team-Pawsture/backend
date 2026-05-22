"""
FastAPI 애플리케이션 진입점
- 모든 라우터를 여기서 등록
- CORS 설정
- 전역 예외 핸들러 (응답 포맷 통일)
"""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

# favorites, notifications, push: 1차 배포 제외, 추후 활성화 예정 (2026-05-13)
# import는 유지해서 다른 코드에서 참조 가능하도록 함 (라우터 노출만 끊음)
from app.routers import (  # noqa: F401
    analyses,
    auth,
    favorites,
    hospitals,
    legacy_uploads,
    notifications,
    pets,
    push,
    videos,
)

app = FastAPI(
    title="성신에이전시 백엔드 API",
    description="반려견 슬개골 탈구 방지 걸음 분석 서비스",
    version="0.1.0"
)


# CORS 설정 — 프론트 도메인만 허용 (BL-7 완료, 2026-05-20)
# 환경변수 CORS_ALLOWED_ORIGINS 콤마 구분. 미설정 시 로컬+vercel 기본값 사용.
# 새 프론트 도메인 추가는 .env 한 줄 변경 + 서버 재기동만 필요.
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,https://pawsture.vercel.app",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# 전역 예외 핸들러 (응답 포맷을 명세서 형식으로 통일)
# ============================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    HTTPException 발생 시 detail 래퍼 제거하고 명세서 포맷으로 반환
    - detail이 dict면 그대로 응답
    - detail이 문자열이면 기본 포맷으로 변환
    """
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "isSuccess": False,
            "code": f"COMMON{exc.status_code}",
            "message": str(exc.detail),
            "result": None
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Pydantic 유효성 검사 실패 시 명세서 포맷으로 반환
    - 422 → 400으로 변경 (명세서 기준)
    - 필드별 에러 메시지를 result에 담음
    - validation_messages.translate_error() 로 한글 매핑 시도, 없으면 Pydantic 영어 fallback
    """
    from app.utils.validation_messages import translate_error

    errors = {}
    for err in exc.errors():
        # loc 예: ('body', 'username') → 'username'
        field = str(err["loc"][-1]) if err.get("loc") else "unknown"
        ko_msg = translate_error(err)
        errors[field] = ko_msg if ko_msg is not None else err.get("msg", "")

    return JSONResponse(
        status_code=400,
        content={
            "isSuccess": False,
            "code": "COMMON400",
            "message": "유효성 검사 실패",
            "result": errors
        }
    )


# 라우터 등록
app.include_router(auth.router)
app.include_router(pets.router)
app.include_router(analyses.router)
# 1차 배포 제외, 추후 활성화 예정 (2026-05-13) — 즐겨찾기/알림 기능
# app.include_router(favorites.router)
# app.include_router(notifications.router)
# app.include_router(push.router)
app.include_router(hospitals.router)
app.include_router(videos.router)  # Phase 2 (2026-05-22): 영상 업로드 분리

# /uploads/* legacy 호환: R2 마이그레이션(2026-05-22 단계 D)으로 StaticFiles mount 제거.
# 기존 URL 형식("/uploads/...")으로 들어오는 GET 요청을 R2 public URL 로 302 redirect.
app.include_router(legacy_uploads.router)


@app.get("/")
def root():
    """헬스 체크 — 서버 살아있는지 확인용"""
    return {"message": "성신에이전시 백엔드 서버 작동 중! 🔥"}
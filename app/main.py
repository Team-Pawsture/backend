"""
FastAPI 애플리케이션 진입점
- 모든 라우터를 여기서 등록
- CORS 설정
- 전역 예외 핸들러 (응답 포맷 통일)
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

# favorites, notifications, push: 1차 배포 제외, 추후 활성화 예정 (2026-05-13)
# import는 유지해서 다른 코드에서 참조 가능하도록 함 (라우터 노출만 끊음)
from app.routers import auth, pets, analyses, favorites, notifications, push, hospitals  # noqa: F401

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

# 정적 파일 서빙 (업로드된 이미지 접근용)
# /uploads/pet_profiles/xxx.jpg 로 접근 가능
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/")
def root():
    """헬스 체크 — 서버 살아있는지 확인용"""
    return {"message": "성신에이전시 백엔드 서버 작동 중! 🔥"}
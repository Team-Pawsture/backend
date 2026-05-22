"""
/uploads/* legacy 호환 라우트 (R2 마이그레이션, 2026-05-22 단계 D)

배경
- 단계 D 이전: app.mount("/uploads", StaticFiles(directory="uploads")) 로 로컬 디스크 서빙
- 단계 D 이후: 실제 파일은 R2 에 있음. 디스크 mount 제거.
- 그러나 DB 의 file_url 형식("/uploads/videos/..." 등)과 프론트가 보내는 요청 형식은 그대로 유지(옵션 W).
- 이 라우터가 그 요청을 받아 R2 public URL 로 302 redirect → 브라우저는 결과적으로 R2 에서 콘텐츠 수신.

라우팅 정책
- 매핑된 prefix("/uploads/videos/", "/uploads/pet_profiles/") → R2 public URL 로 302
- 매핑 없음 → 404 (BASE_URL fallback 으로 무한 redirect 되는 것 방지)
- Swagger 스펙에는 노출하지 않음 (include_in_schema=False) — legacy 호환용
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.utils.url_helper import build_absolute_url


router = APIRouter(tags=["uploads (legacy redirect)"])


@router.get("/uploads/{path:path}", include_in_schema=False)
async def redirect_to_r2(path: str):
    """
    /uploads/{path} → R2 public URL 로 302 Found.
    302(Found, 임시) 사용 — 운영 중 R2 도메인 변경 가능성 있어 영구 redirect(301) 회피.
    """
    relative = f"/uploads/{path}"
    target = build_absolute_url(relative)

    # build_absolute_url 은 매핑 없는 prefix 면 BASE_URL prefix 를 붙여 돌려준다.
    # 그걸 그대로 redirect 하면 무한 루프 → R2 host(https://) 인 경우에만 redirect.
    if not target or not target.startswith("https://"):
        raise HTTPException(status_code=404, detail="Not Found")

    return RedirectResponse(url=target, status_code=302)

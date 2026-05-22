"""
URL 조립 유틸리티
- 상대 경로(예: "/uploads/pet_profiles/xxx.jpg")를 절대 URL로 변환

R2 마이그레이션 (2026-05-22, 단계 B/C)
- /uploads/videos/*       → R2 public URL (videos/* 키)
- /uploads/pet_profiles/* → R2 public URL (pet_profiles/* 키)
- 그 외 상대경로          → BASE_URL prefix (fallback, 기존 동작)
- http(s):// 시작         → 그대로 통과 (이중 prefix 방지)
"""

import os


# 상대경로 prefix → R2 객체 키 prefix 매핑.
# 단일 진실 출처: 라우터들이 DB 에 저장하는 file_url 형식("/uploads/<dir>/<file>")과
# 이 모듈만 알면 됨. r2_client 는 키 prefix 를 모름.
_R2_PREFIX_MAP = {
    "/uploads/videos/": "videos/",
    "/uploads/pet_profiles/": "pet_profiles/",
}


def build_absolute_url(relative_path: str | None) -> str | None:
    """
    상대 경로 앞에 절대 URL 을 붙여 반환한다.
    - relative_path 가 None / 빈 문자열 → 그대로 반환
    - http(s):// 시작 → 그대로 반환 (이중 prefix 방지)
    - _R2_PREFIX_MAP 매칭 → r2_client.build_public_url() 로 R2 public URL 조립
    - 그 외 → BASE_URL (default http://localhost:8000) prefix
    """
    if not relative_path:
        return relative_path

    if relative_path.startswith("http://") or relative_path.startswith("https://"):
        return relative_path

    # R2 라우팅: 매칭되는 prefix 가 있으면 R2 public URL 로 위임.
    for uploads_prefix, r2_prefix in _R2_PREFIX_MAP.items():
        if relative_path.startswith(uploads_prefix):
            # lazy import: r2_client 는 모듈 로드 시점에 R2 env 5종을 강제 검증한다.
            # ai_client 등이 module-level 로 url_helper 를 import 하므로,
            # 부트 단계에서 R2 env 미설정 환경이라도 앱 자체는 살아있도록 함수 내부에서 import.
            from app.utils import r2_client

            r2_key = r2_prefix + relative_path[len(uploads_prefix):]
            return r2_client.build_public_url(r2_key)

    base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    path = relative_path if relative_path.startswith("/") else f"/{relative_path}"
    return f"{base_url}{path}"

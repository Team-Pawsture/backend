"""
URL 조립 유틸리티
- 상대 경로(예: "/uploads/pet_profiles/xxx.jpg")를 BASE_URL 기준 절대 URL로 변환
"""

import os


def build_absolute_url(relative_path: str | None) -> str | None:
    """
    상대 경로 앞에 BASE_URL을 붙여 절대 URL을 만든다.
    - relative_path가 None이거나 빈 문자열이면 그대로 반환
    - 이미 http(s)://로 시작하면 그대로 반환 (이중 prefix 방지)
    - BASE_URL이 설정 안 됐으면 http://localhost:8000 기본값 사용
    """
    if not relative_path:
        return relative_path

    if relative_path.startswith("http://") or relative_path.startswith("https://"):
        return relative_path

    base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    path = relative_path if relative_path.startswith("/") else f"/{relative_path}"
    return f"{base_url}{path}"

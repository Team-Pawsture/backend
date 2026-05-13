"""
파일 업로드 처리 유틸리티
- 이미지 파일 검증 (타입, 크기)
- 안전한 파일명 생성 (충돌 방지)
- 기존 파일 삭제
"""

import os
import uuid
from pathlib import Path
from fastapi import UploadFile


# ============================================
# 설정값
# ============================================
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = Path("uploads/pet_profiles")


# ============================================
# 파일 형식 검증
# ============================================
def is_allowed_extension(filename: str) -> bool:
    """파일명에서 확장자 추출 후 허용 목록과 비교"""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


# ============================================
# 안전한 파일명 생성
# ============================================
def generate_safe_filename(pet_id: int, original_filename: str) -> str:
    """
    파일명 충돌 방지를 위한 고유 파일명 생성
    예: pet_1_a3f2c1d9.jpg
    """
    ext = Path(original_filename).suffix.lower()
    unique_id = uuid.uuid4().hex[:8]  # 8자리 무작위
    return f"pet_{pet_id}_{unique_id}{ext}"


# ============================================
# 이미지 저장 (파일 시스템에 쓰기)
# ============================================
async def save_pet_image(pet_id: int, file: UploadFile) -> str:
    """
    1. 파일 내용 읽기 (크기 체크 위해)
    2. 크기 검증 (10MB 이하)
    3. 안전한 파일명 생성
    4. uploads/pet_profiles/ 에 저장
    5. 저장된 경로 반환 (DB에 넣을 값)
    
    반환: "/uploads/pet_profiles/pet_1_xxx.jpg"
    """
    # 1. 파일 내용 읽기
    contents = await file.read()
    
    # 2. 크기 검증
    if len(contents) > MAX_FILE_SIZE:
        raise ValueError("파일 크기가 10MB를 초과합니다.")
    
    if len(contents) == 0:
        raise ValueError("빈 파일입니다.")
    
    # 3. 안전한 파일명 생성
    safe_filename = generate_safe_filename(pet_id, file.filename)
    
    # 4. 디스크에 저장
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)  # 폴더 없으면 만들기
    file_path = UPLOAD_DIR / safe_filename
    with open(file_path, "wb") as f:
        f.write(contents)
    
    # 5. DB에 저장할 경로 (URL 형식으로 변환)
    return f"/uploads/pet_profiles/{safe_filename}"


# ============================================
# 기존 이미지 삭제
# ============================================
def delete_pet_image(image_url: str) -> None:
    """
    DB의 profile_image_url을 받아서 실제 파일 삭제
    예: "/uploads/pet_profiles/pet_1_xxx.jpg" → 파일 삭제
    """
    if not image_url:
        return
    
    # URL의 맨 앞 "/" 제거 후 경로로 변환
    file_path = Path(image_url.lstrip("/"))
    
    if file_path.exists():
        try:
            file_path.unlink()  # 파일 삭제
        except OSError:
            # 삭제 실패해도 무시 (예: 권한 문제)
            # 새 파일 업로드는 정상 진행
            pass
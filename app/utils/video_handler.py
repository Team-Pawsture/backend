"""
영상 파일 업로드 처리 유틸리티
- 영상 파일 검증 (형식, 크기)
- 안전한 파일명 생성 (충돌 방지)
- 영상 저장 + 삭제
"""

import uuid
from pathlib import Path
from fastapi import UploadFile


# ============================================
# 설정값
# ============================================
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi"}
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
VIDEO_UPLOAD_DIR = Path("uploads/analysis_videos")


# ============================================
# 영상 형식 검증
# ============================================
def is_allowed_video_extension(filename: str) -> bool:
    """파일명에서 확장자 추출 후 허용 목록과 비교"""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_VIDEO_EXTENSIONS


# ============================================
# 안전한 파일명 생성
# ============================================
def generate_safe_video_filename(pet_id: int, original_filename: str) -> str:
    """
    파일명 충돌 방지를 위한 고유 파일명 생성
    예: analysis_pet1_a3f2c1d9.mp4
    """
    ext = Path(original_filename).suffix.lower()
    unique_id = uuid.uuid4().hex[:8]  # 8자리 무작위
    return f"analysis_pet{pet_id}_{unique_id}{ext}"


# ============================================
# 영상 저장 (파일 시스템에 쓰기)
# ============================================
async def save_analysis_video(pet_id: int, file: UploadFile) -> dict:
    """
    1. 파일 내용 읽기 (크기 체크 위해)
    2. 크기 검증 (100MB 이하)
    3. 안전한 파일명 생성
    4. uploads/analysis_videos/ 에 저장
    5. 저장된 정보 반환
    
    반환:
    {
        "file_path": "uploads/analysis_videos/analysis_pet1_xxx.mp4",
        "url_path": "/uploads/analysis_videos/analysis_pet1_xxx.mp4",
        "filename": "analysis_pet1_xxx.mp4",
        "size_bytes": 1234567
    }
    """
    # 1. 파일 내용 읽기
    contents = await file.read()
    file_size = len(contents)
    
    # 2. 크기 검증
    if file_size > MAX_VIDEO_SIZE:
        raise ValueError(f"파일 크기가 100MB를 초과합니다. (현재 {file_size / 1024 / 1024:.1f}MB)")
    
    if file_size == 0:
        raise ValueError("빈 파일입니다.")
    
    # 3. 안전한 파일명 생성
    safe_filename = generate_safe_video_filename(pet_id, file.filename)
    
    # 4. 디스크에 저장
    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)  # 폴더 없으면 만들기
    file_path = VIDEO_UPLOAD_DIR / safe_filename
    with open(file_path, "wb") as f:
        f.write(contents)
    
    # 5. 결과 반환
    return {
        "file_path": str(file_path),                      # AI 호출 시 사용 (로컬 경로)
        "url_path": f"/uploads/analysis_videos/{safe_filename}",  # 클라이언트 접근용 URL
        "filename": safe_filename,
        "size_bytes": file_size,
    }


# ============================================
# 영상 삭제
# ============================================
def delete_analysis_video(file_path: str) -> None:
    """
    저장된 영상 파일 삭제
    - file_path: 로컬 경로 또는 URL 경로 둘 다 처리
    
    사용 시점:
    - 분석 실패 시 (영상 보존 불필요)
    - 분석 결과 삭제 시
    - 일정 기간 후 정리 (배치 작업)
    """
    if not file_path:
        return
    
    # URL 경로면 로컬 경로로 변환
    if file_path.startswith("/uploads/"):
        path = Path(file_path.lstrip("/"))
    else:
        path = Path(file_path)
    
    if path.exists():
        try:
            path.unlink()  # 파일 삭제
        except OSError:
            # 삭제 실패해도 무시 (예: 권한 문제)
            pass
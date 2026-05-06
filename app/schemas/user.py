"""
User 관련 Pydantic 스키마
- 요청(Request) / 응답(Response) 데이터의 형식과 유효성 검사 정의
- DB 모델(SQLAlchemy)과 분리해서 관리
"""

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# 회원가입 요청 (Request Body)
# ============================================
class UserSignupRequest(BaseModel):
    username: str = Field(..., min_length=4, max_length=20, description="아이디 (4~20자)")
    password: str = Field(..., min_length=8, max_length=100, description="비밀번호 (8자 이상)")
    name: str = Field(..., min_length=1, max_length=50, description="보호자 성명")


# ============================================
# 회원가입 응답 (Response)
# ============================================
class UserSignupResponse(BaseModel):
    user_id: int
    username: str
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
    # ↑ SQLAlchemy 객체 → Pydantic 자동 변환 허용


# ============================================
# 공통 응답 포맷 (isSuccess / code / message / result)
# ============================================
class CommonResponse(BaseModel):
    isSuccess: bool
    code: str
    message: str
    result: dict | list | None = None

# ============================================
# 로그인 요청 (Request Body)
# ============================================
class UserLoginRequest(BaseModel):
    username: str = Field(..., description="아이디")
    password: str = Field(..., description="비밀번호")
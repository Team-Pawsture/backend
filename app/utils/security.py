"""
보안 관련 유틸리티
- 비밀번호 해싱 / 검증 (bcrypt)
- JWT 토큰 생성 / 검증 (로그인 API에서 사용 예정)
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from jose import jwt, JWTError
from passlib.context import CryptContext

load_dotenv()

# ============================================
# 비밀번호 해싱 설정
# ============================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """평문 비밀번호 → 해시값 변환 (회원가입 시 사용)"""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """평문 비밀번호와 해시값 비교 (로그인 시 사용)"""
    return pwd_context.verify(plain_password, hashed_password)


# ============================================
# JWT 토큰 설정
# ============================================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 60))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """JWT 토큰 검증 + 디코딩 (인증 미들웨어에서 사용)"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None

# ============================================
# JWT 인증 의존성 (FastAPI Depends 용)
# ============================================
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User


# Authorization 헤더에서 Bearer 토큰 추출하는 도구
security_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    현재 로그인된 사용자 조회 (JWT 검증 + DB 조회)
    - 인증이 필요한 모든 API에서 Depends로 사용
    - 토큰 없거나, 만료, 위조 시 → 401 에러
    """
    # 1. 토큰 디코딩
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "isSuccess": False,
                "code": "USER401",
                "message": "유효하지 않은 토큰입니다.",
                "result": None
            }
        )
    
    # 2. payload에서 user_id 추출
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "isSuccess": False,
                "code": "USER401",
                "message": "유효하지 않은 토큰입니다.",
                "result": None
            }
        )
    
    # 3. DB에서 사용자 조회
    user = db.query(User).filter(User.user_id == int(user_id_str)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "isSuccess": False,
                "code": "USER401",
                "message": "유효하지 않은 토큰입니다.",
                "result": None
            }
        )
    
    return user
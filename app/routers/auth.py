"""
인증 관련 API 라우터
- POST /auth/signup : 회원가입 ✅ 구현 완료
- POST /auth/login : 로그인 + JWT 발급 ✅ 구현 완료
- GET /auth/me : 내 정보 조회 ✅ 구현 완료
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserSignupRequest, UserLoginRequest, CommonResponse
from app.utils.security import hash_password, verify_password, create_access_token, get_current_user
from app.utils.datetime_helper import to_kst_iso


router = APIRouter(prefix="/auth", tags=["인증"])


@router.post("/signup", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def signup(request: UserSignupRequest, db: Session = Depends(get_db)):
    """
    회원가입
    - username 중복 체크
    - 비밀번호 해싱 후 저장
    """
    # 1. username 중복 체크
    existing_user = db.query(User).filter(User.username == request.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "isSuccess": False,
                "code": "USER409",
                "message": "이미 사용 중인 아이디입니다.",
                "result": None
            }
        )

    # 2. 비밀번호 해싱
    hashed_pw = hash_password(request.password)

    # 3. DB에 저장
    new_user = User(
        username=request.username,
        password=hashed_pw,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 4. 성공 응답 (명세서 형식 그대로)
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="회원 가입에 성공하였습니다.",
        result={
            "user_id": new_user.user_id,
            "username": new_user.username,
        }
    )

@router.post("/login", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """
    로그인
    - username + password 검증
    - 성공 시 JWT 액세스 토큰 발급
    """
    # 1. username으로 사용자 찾기
    user = db.query(User).filter(User.username == request.username).first()
    
    # 2. 사용자 없거나 비밀번호 틀리면 → 401
    if not user or not verify_password(request.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "isSuccess": False,
                "code": "USER401",
                "message": "아이디 또는 비밀번호가 올바르지 않습니다.",
                "result": None
            }
        )
    
    # 3. JWT 토큰 생성 (payload에 user_id 담기)
    access_token = create_access_token(data={"sub": str(user.user_id)})
    
    # 4. 성공 응답 (명세서 형식 그대로)
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "user": {
                "user_id": user.user_id,
                "username": user.username,
            }
        }
    )

@router.get("/me", response_model=CommonResponse, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)):
    """
    내 정보 조회
    - JWT 토큰으로 본인 확인
    - 앱 시작 시 자동 로그인 체크용
    """
    return CommonResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공입니다.",
        result={
            "user_id": current_user.user_id,
            "username": current_user.username,
            "created_at": to_kst_iso(current_user.created_at)
        }
    )
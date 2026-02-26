from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError

from database import get_db
from models import User
from security import (
    verify_password, hash_password, create_access_token, decode_token,
    create_refresh_token, verify_refresh_token, revoke_refresh_token, revoke_user_tokens,
)
from schemas import (
    LoginRequest, TokenResponse, UserResponse,
    RefreshTokenRequest, ChangePasswordRequest,
)
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if user.locked_until and user.locked_until > datetime.utcnow():
        mins = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
        raise HTTPException(status_code=423, detail=f"账号已锁定，请 {mins} 分钟后重试")

    if not verify_password(body.password, user.hashed_password):
        user.failed_login_attempts += 1
        user.last_failed_login = datetime.utcnow()
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.commit()
        remaining = max(0, 5 - user.failed_login_attempts)
        raise HTTPException(status_code=401, detail=f"邮箱或密码错误，还可尝试 {remaining} 次")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="用户未激活")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, db)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Exchange a refresh token for new access + refresh tokens (rotation)."""
    rt = verify_refresh_token(body.refresh_token, db)
    if not rt:
        raise HTTPException(status_code=401, detail="无效或已过期的刷新令牌")

    user = db.query(User).filter(User.id == rt.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")

    # Revoke old refresh token (rotation)
    revoke_refresh_token(body.refresh_token, db)

    # Issue new tokens
    access_token = create_access_token(user.id, user.role)
    new_refresh_token = create_refresh_token(user.id, db)
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
def logout(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Revoke a refresh token."""
    revoke_refresh_token(body.refresh_token, db)
    return {"detail": "已登出"}


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码错误")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码长度至少 8 个字符")

    current_user.hashed_password = hash_password(body.new_password)
    current_user.is_default_password = False
    current_user.password_changed_at = datetime.utcnow()
    db.commit()

    # Revoke all existing refresh tokens (force re-login on other devices)
    revoke_user_tokens(current_user.id, db)

    # Issue fresh tokens
    access_token = create_access_token(current_user.id, current_user.role)
    refresh_token = create_refresh_token(current_user.id, db)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(current_user),
    )

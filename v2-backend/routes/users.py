"""
User management endpoints — superadmin only.
"""

import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User
from security import require_role, hash_password, ROLE_LEVELS, revoke_user_tokens
from schemas import UserCreateRequest, UserUpdateRequest, UserListResponse

require_superadmin = require_role("superadmin")

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserListResponse])
def list_users(
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """List all users."""
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserListResponse, status_code=201)
def create_user(
    body: UserCreateRequest,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Create a new user."""
    if body.role not in ROLE_LEVELS:
        raise HTTPException(400, f"无效角色: {body.role}，可选: {', '.join(ROLE_LEVELS.keys())}")

    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(409, f"邮箱 '{body.email}' 已存在")

    user = User(
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=body.role,
        is_active=True,
        is_default_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserListResponse)
def update_user(
    user_id: int,
    body: UserUpdateRequest,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Update user info (name, role, active status)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    if body.role is not None:
        if body.role not in ROLE_LEVELS:
            raise HTTPException(400, f"无效角色: {body.role}")
        user.role = body.role

    if body.full_name is not None:
        user.full_name = body.full_name

    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            revoke_user_tokens(user_id, db)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Soft-delete: deactivate a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.id == current_user.id:
        raise HTTPException(400, "不能停用自己")

    user.is_active = False
    revoke_user_tokens(user_id, db)
    db.commit()
    return {"detail": "用户已停用"}


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    current_user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Reset a user's password to a default temporary one."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(8))
    user.hashed_password = hash_password(temp_password)
    user.is_default_password = True
    revoke_user_tokens(user_id, db)
    db.commit()
    return {"detail": f"密码已重置为临时密码: {temp_password}"}

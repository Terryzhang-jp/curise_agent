from datetime import datetime, timedelta
from typing import Optional
import hashlib
import uuid

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─── Role Levels ─────────────────────────────────────────────

ROLE_LEVELS = {"superadmin": 100, "admin": 50, "finance": 30, "employee": 20}


# ─── Password ────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─── Access Token ─────────────────────────────────────────────

def create_access_token(user_id: int, role: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "exp": expire,
        "sub": str(user_id),
        "role": role,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ─── Refresh Token ────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_refresh_token(user_id: int, db: Session) -> str:
    from models import RefreshToken

    token = str(uuid.uuid4())
    rt = RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(token),
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    db.commit()
    return token


def verify_refresh_token(token: str, db: Session):
    from models import RefreshToken

    token_hash = _hash_token(token)
    rt = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow(),
    ).first()
    return rt


def revoke_refresh_token(token: str, db: Session):
    from models import RefreshToken

    token_hash = _hash_token(token)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if rt:
        rt.is_revoked = True
        db.commit()


def revoke_user_tokens(user_id: int, db: Session):
    from models import RefreshToken

    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False,
    ).update({"is_revoked": True})
    db.commit()


# ─── Role-based Access ────────────────────────────────────────

def require_role(*allowed_roles: str):
    """Dependency factory: restrict endpoint to specific roles."""
    from models import User
    from routes.auth import get_current_user

    def checker(user: User = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(403, "权限不足")
        return user

    return checker

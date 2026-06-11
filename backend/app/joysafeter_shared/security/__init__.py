"""Security utilities package compatibility exports."""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from pydantic import BaseModel

from app.joysafeter_shared.config.settings import settings


class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    iat: datetime
    type: str = "access"
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    role: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def generate_password_reset_token() -> tuple[str, datetime]:
    token = generate_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    return token, expires


def generate_email_verify_token() -> tuple[str, datetime]:
    token = generate_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=72)
    return token, expires


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    plain_password = plain_password.lower().strip()
    hashed_password = hashed_password.lower().strip()
    if len(plain_password) != 64 or not all(c in "0123456789abcdef" for c in plain_password):
        return False
    if len(hashed_password) != 64 or not all(c in "0123456789abcdef" for c in hashed_password):
        return False
    return hmac.compare_digest(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    password = password.strip().lower()
    if len(password) != 64 or not all(c in "0123456789abcdef" for c in password):
        raise ValueError("Password must be a SHA-256 hash (64 hex characters)")
    return password


def create_access_token(
    subject: str | Any,
    expires_delta: Optional[timedelta] = None,
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
    role: Optional[str] = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if org_id:
        to_encode["org_id"] = org_id
    if project_id:
        to_encode["project_id"] = project_id
    if role:
        to_encode["role"] = role
    return str(jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm))


def generate_refresh_token(length: int = 64) -> str:
    return secrets.token_hex(length)


def create_csrf_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "csrf",
    }
    return str(jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm))


def decode_token(token: str) -> Optional[TokenPayload]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return TokenPayload(**payload)
    except JWTError:
        return None


__all__ = [
    "Token",
    "TokenPayload",
    "create_access_token",
    "create_csrf_token",
    "decode_token",
    "generate_email_verify_token",
    "generate_password_reset_token",
    "generate_refresh_token",
    "generate_token",
    "get_password_hash",
    "verify_password",
]

"""Security utilities."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from app.joysafeter_shared.config.settings import settings

_BCRYPT_ROUNDS = 12


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


def hash_security_token(token: str) -> str:
    if not token:
        raise ValueError("Security token must not be empty")
    return hashlib.sha256(f"joysafeter-security-token:v1:{token}".encode()).hexdigest()


def _password_material(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False

    try:
        return bcrypt.checkpw(_password_material(plain_password), hashed_password.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def get_password_hash(password: str) -> str:
    if not password:
        raise ValueError("Password must not be empty")
    return bcrypt.hashpw(_password_material(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


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
    "hash_security_token",
    "verify_password",
]

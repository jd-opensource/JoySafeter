"""Security utilities — JWT and password handling."""

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from pydantic import BaseModel

from .settings import settings


def generate_token(length: int = 32) -> str:
    """Generate a random URL-safe token."""
    return secrets.token_urlsafe(length)


def generate_password_reset_token() -> tuple[str, datetime]:
    """Generate a password reset token and expiration time."""
    token = generate_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)  # valid for 24 hours
    return token, expires


def generate_email_verify_token() -> tuple[str, datetime]:
    """Generate an email verification token and expiration time."""
    token = generate_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=72)  # valid for 72 hours
    return token, expires


class TokenPayload(BaseModel):
    """Token payload."""

    sub: str  # user_id
    exp: datetime
    iat: datetime
    type: str = "access"


class Token(BaseModel):
    """Token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password (SHA-256 format only).

    Both plain_password and hashed_password must be SHA-256 hex strings
    (64 hex characters). Uses constant-time comparison to prevent timing attacks.
    """
    if not plain_password or not hashed_password:
        return False

    # normalize input (lowercase)
    plain_password = plain_password.lower().strip()
    hashed_password = hashed_password.lower().strip()

    # validate format (must be SHA-256)
    if len(plain_password) != 64 or not all(
        c in "0123456789abcdef" for c in plain_password
    ):  # pragma: allowlist secret
        return False

    if len(hashed_password) != 64 or not all(c in "0123456789abcdef" for c in hashed_password):
        return False

    # compare two SHA-256 hashes using constant-time comparison to prevent timing attacks
    return hmac.compare_digest(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Get password hash (SHA-256 format only).

    The input password must be a SHA-256 hex string (64 hex characters).
    Returns the normalized lowercase SHA-256 hash.
    """
    password = password.strip().lower()

    # validate format (must be SHA-256)
    if len(password) != 64 or not all(c in "0123456789abcdef" for c in password):
        raise ValueError("Password must be a SHA-256 hash (64 hex characters)")

    return password


def create_access_token(subject: str | Any, expires_delta: Optional[timedelta] = None) -> str:
    """Create an access token."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }

    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return str(encoded_jwt)


def generate_refresh_token(length: int = 64) -> str:
    """Generate a refresh token (random string, stored in Redis)."""
    return secrets.token_hex(length)


def create_csrf_token(user_id: str) -> str:
    """Create a CSRF token (JWT)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "csrf",
    }

    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return str(encoded_jwt)


def decode_token(token: str) -> Optional[TokenPayload]:
    """Decode a JWT token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return TokenPayload(**payload)
    except JWTError:
        return None

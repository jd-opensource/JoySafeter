"""
安全相关 - JWT 和密码处理
"""

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from pydantic import BaseModel

from .settings import settings


def generate_token(length: int = 32) -> str:
    """生成随机令牌"""
    return secrets.token_urlsafe(length)


def generate_password_reset_token() -> tuple[str, datetime]:
    """生成密码重置令牌和过期时间"""
    token = generate_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)  # 24小时有效
    return token, expires


def generate_email_verify_token() -> tuple[str, datetime]:
    """生成邮箱验证令牌和过期时间"""
    token = generate_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=72)  # 72小时有效
    return token, expires


class TokenPayload(BaseModel):
    """Token 载荷"""

    sub: str  # user_id
    exp: datetime
    iat: datetime
    type: str = "access"


class Token(BaseModel):
    """Token 响应"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码（只支持 SHA-256 格式）

    接收的 plain_password 和 hashed_password 都必须是 SHA-256 哈希值
    （64个字符的十六进制字符串）

    使用安全的字符串比较防止时序攻击
    """
    if not plain_password or not hashed_password:
        return False

    # 标准化输入（小写）
    plain_password = plain_password.lower().strip()
    hashed_password = hashed_password.lower().strip()

    # 验证格式（必须是 SHA-256）
    if len(plain_password) != 64 or not all(c in "0123456789abcdef" for c in plain_password):
        return False

    if len(hashed_password) != 64 or not all(c in "0123456789abcdef" for c in hashed_password):
        return False

    # 直接比较两个 SHA-256 哈希值
    # 使用 hmac.compare_digest 防止时序攻击
    return hmac.compare_digest(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    获取密码哈希（只支持 SHA-256 格式）

    接收的 password 必须是 SHA-256 哈希值（64个字符的十六进制字符串）
    直接返回标准化后的 SHA-256 哈希值
    """
    password = password.strip().lower()

    # 验证格式（必须是 SHA-256）
    if len(password) != 64 or not all(c in "0123456789abcdef" for c in password):
        raise ValueError("Password must be a SHA-256 hash (64 hex characters)")

    return password


def create_access_token(subject: str | Any, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
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
    """生成刷新令牌（随机字符串，存储在 Redis）"""
    return secrets.token_hex(length)


def create_csrf_token(user_id: str) -> str:
    """创建 CSRF token（JWT）"""
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
    """解码令牌"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return TokenPayload(**payload)
    except JWTError:
        return None


def verify_csrf_token(csrf_token: str, user_id: str) -> bool:
    """
    验证 CSRF token

    Args:
        csrf_token: 从请求头获取的 CSRF token
        user_id: 当前登录用户的 ID

    Returns:
        True if valid, False otherwise
    """
    if not csrf_token or not user_id:
        return False

    try:
        payload = jwt.decode(csrf_token, settings.secret_key, algorithms=[settings.algorithm])

        # 验证 token 类型
        if payload.get("type") != "csrf":
            return False

        # 验证用户 ID 匹配
        if payload.get("sub") != str(user_id):
            return False

        # 验证过期时间（jwt.decode 已自动检查）
        return True

    except JWTError:
        return False

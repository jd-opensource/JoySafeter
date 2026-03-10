"""
OpenAPI Token 认证依赖

通过 Authorization: Bearer <api_key> 验证请求，
查找 api_key 表中的记录，返回关联的 User 对象。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenException, UnauthorizedException
from app.core.database import get_db
from app.models.api_key import ApiKey
from app.models.auth import AuthUser as User


async def get_api_key_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, ApiKey]:
    """
    从 Authorization header 中提取 API Key 并验证。

    Returns:
        (User, ApiKey) 元组

    Raises:
        UnauthorizedException: key 缺失 / 无效 / 过期
    """
    if not authorization:
        raise UnauthorizedException("Missing Authorization header")

    # 支持 "Bearer xxx" 和纯 "xxx"
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        raw_key = parts[1].strip()
    else:
        raw_key = authorization.strip()

    if not raw_key:
        raise UnauthorizedException("Missing API key")

    # 查找 key
    result = await db.execute(select(ApiKey).where(ApiKey.key == raw_key))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise UnauthorizedException("Invalid API key")

    # 过期检查
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise UnauthorizedException("API key has expired")

    # 加载关联用户
    user_result = await db.execute(select(User).where(User.id == api_key.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise UnauthorizedException("API key owner not found")
    if not user.is_active:
        raise ForbiddenException("User account is inactive")

    # 更新 last_used
    api_key.last_used = datetime.now(timezone.utc)
    await db.commit()

    return user, api_key

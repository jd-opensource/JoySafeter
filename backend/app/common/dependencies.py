"""
公共依赖项
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Optional

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenException, NotFoundException, UnauthorizedException
from app.core.database import get_db
from app.core.security import decode_token, verify_csrf_token
from app.core.settings import settings
from app.models.auth import AuthUser as User
from app.models.organization import Member as OrgMember
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository
from app.services.auth_session_service import AuthSessionService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_optional_request(request: Request) -> Request:
    """Dependency to provide Request object."""
    return request


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话"""
    async for session in get_db():
        yield session


async def get_current_user(
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
    request: Annotated[Request, Depends(get_optional_request)] = None,  # type: ignore[assignment]
) -> User:
    """
    获取当前用户（必须登录）
    支持两种认证方式：
    1. JWT token（优先）：解码 JWT token 获取用户 ID
    2. Session token（兼容）：从 auth.session 表验证
    同时支持通过 Cookie 传递 token（优先使用配置的 cookie_name）
    """
    cookie_token = None
    try:
        if request:
            # 优先从配置的 cookie_name 读取，然后尝试其他可能的名称
            cookie_token = (
                request.cookies.get(settings.cookie_name)  # 优先使用配置的 cookie 名称
                or request.cookies.get("session-token")
                or request.cookies.get("session_token")
                or request.cookies.get("access_token")
                or request.cookies.get("Authorization")
                or request.cookies.get("auth_token")
            )
    except Exception:
        pass
    token = token or cookie_token
    if not token:
        raise UnauthorizedException("Missing credentials")

    # 首先尝试作为 JWT token 验证（JWT 模式）
    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        result = await db.execute(select(User).where(User.id == str(user_id)))
        user = result.scalar_one_or_none()
        if user is None:
            raise UnauthorizedException("User not found")
        if not user.is_active:
            raise UnauthorizedException("User is inactive")
        return user

    # 如果 JWT token 验证失败，尝试作为 session token 验证（向后兼容）
    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        result = await db.execute(select(User).where(User.id == session.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise UnauthorizedException("User not found")
        if not user.is_active:
            raise UnauthorizedException("User is inactive")
        return user

    raise UnauthorizedException("Could not validate credentials")


async def get_current_user_optional(
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
    request: Annotated[Request, Depends(get_optional_request)] = None,  # type: ignore[assignment]
) -> Optional[User]:
    """获取当前用户（可选，未登录返回 None），同时支持 Cookie 里的 token。"""
    cookie_token = None
    try:
        if request:
            # 优先从配置的 cookie_name 读取，然后尝试其他可能的名称
            cookie_token = (
                request.cookies.get(settings.cookie_name)  # 优先使用配置的 cookie 名称
                or request.cookies.get("session-token")
                or request.cookies.get("session_token")
                or request.cookies.get("access_token")
                or request.cookies.get("Authorization")
                or request.cookies.get("auth_token")
            )
    except Exception:
        pass
    token = token or cookie_token
    if not token:
        return None

    # 优先 JWT token
    payload = decode_token(token)
    if payload:
        user_id = payload.sub
        result = await db.execute(select(User).where(User.id == str(user_id)))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
        return None

    # 回退 session token
    session_service = AuthSessionService(db)
    session = await session_service.get_session_by_token(token)
    if session:
        result = await db.execute(select(User).where(User.id == session.user_id))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
        return None

    return None


def require_roles(*roles: str):
    """角色权限检查装饰器"""

    async def check_roles(current_user: User = Depends(get_current_user)):
        if current_user.is_superuser:
            return current_user
        return current_user

    return Depends(check_roles)


# --------------------------------------------------------------------------- #
# Workspace / Organization 角色装饰器
# --------------------------------------------------------------------------- #
def _role_rank(role: WorkspaceMemberRole) -> int:
    order = [
        WorkspaceMemberRole.viewer,
        WorkspaceMemberRole.member,
        WorkspaceMemberRole.admin,
        WorkspaceMemberRole.owner,
    ]
    try:
        return order.index(role)
    except ValueError:
        return -1


def require_workspace_role(min_role: WorkspaceMemberRole):
    """
    用于路由层的依赖，校验当前用户在指定 workspace_id 上的角色 >= min_role。
    需确保路径参数/查询参数中有 workspace_id。
    """

    async def checker(
        workspace_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.is_superuser:
            return current_user

        ws_repo = WorkspaceRepository(db)
        member_repo = WorkspaceMemberRepository(db)

        workspace = await ws_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        if workspace.owner_id == current_user.id:
            return current_user

        member = await member_repo.get_member(workspace_id, current_user.id)
        if not member:
            raise ForbiddenException("No access to workspace")

        if _role_rank(member.role) < _role_rank(min_role):
            raise ForbiddenException("Insufficient workspace permission")

        return current_user

    return Depends(checker)


def require_org_role(min_role: str):
    """
    校验当前用户在指定 organization_id 上的角色（简单字符串比较，owner > admin > member）。
    需确保路径/查询中有 organization_id。
    """
    role_order = ["member", "admin", "owner"]

    def _rank(r: str) -> int:
        try:
            return role_order.index(r)
        except ValueError:
            return -1

    async def checker(
        organization_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.is_superuser:
            return current_user

        result = await db.execute(
            select(OrgMember).where(
                OrgMember.organization_id == organization_id,
                OrgMember.user_id == current_user.id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise ForbiddenException("No access to organization")
        if _rank(member.role) < _rank(min_role):
            raise ForbiddenException("Insufficient organization permission")
        return current_user

    return Depends(checker)


CurrentUser = Annotated[User, Depends(get_current_user)]


# --------------------------------------------------------------------------- #
# CSRF Protection
# --------------------------------------------------------------------------- #


async def verify_csrf(
    request: Request,
    current_user: User = Depends(get_current_user),
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
) -> User:
    """
    验证 CSRF token（用于状态修改操作）

    仅对以下方法强制验证 CSRF：POST, PUT, PATCH, DELETE
    GET, HEAD, OPTIONS 方法不需要 CSRF 保护

    安全设计：
    - CSRF token 通过登录响应返回，存储在前端内存中
    - 前端通过 X-CSRF-Token header 发送 token
    - 不使用 Cookie 存储，避免 XSS 窃取

    Args:
        request: FastAPI Request 对象
        current_user: 当前登录用户（由 get_current_user 提供）
        x_csrf_token: 从请求头 X-CSRF-Token 获取的 CSRF token

    Returns:
        当前用户对象

    Raises:
        UnauthorizedException: CSRF token 缺失或无效
    """
    # 只对状态修改操作验证 CSRF
    if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        # 从请求头获取 CSRF token
        csrf_token = x_csrf_token

        # CSRF token 必须存在于请求头
        if not csrf_token:
            raise UnauthorizedException("Missing CSRF token")

        # 验证 CSRF token
        if not verify_csrf_token(csrf_token, current_user.id):
            raise UnauthorizedException("Invalid CSRF token")

    return current_user


# 带 CSRF 保护的当前用户类型注解
CurrentUserWithCSRF = Annotated[User, Depends(verify_csrf)]

"""
OAuth/OIDC 认证 API 端点

提供 OAuth 登录流程的 API：
- GET /oauth/providers - 获取已启用的 OAuth 提供商列表
- GET /oauth/{provider} - 发起 OAuth 授权流程
- GET /oauth/{provider}/callback - 处理 OAuth 回调
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_db
from app.common.exceptions import BadRequestException
from app.core.oauth_config import get_oauth_config
from app.core.security import create_access_token, create_csrf_token, generate_refresh_token
from app.core.settings import settings
from app.services.oauth_service import OAuthService

LOG_PREFIX = "[OAuthAPI]"
router = APIRouter(prefix="/v1/auth/oauth", tags=["OAuth"])


# ==================== Response Models ====================


class OAuthProviderInfo(BaseModel):
    """OAuth 提供商信息（不含敏感信息）"""

    id: str
    display_name: str
    icon: str


class OAuthProvidersResponse(BaseModel):
    """OAuth 提供商列表响应"""

    providers: List[OAuthProviderInfo]


# ==================== API Endpoints ====================


@router.get("/providers", response_model=OAuthProvidersResponse)
async def list_oauth_providers() -> OAuthProvidersResponse:
    """
    获取已启用的 OAuth 提供商列表

    用于前端动态渲染 SSO 登录按钮。
    """
    oauth_config = get_oauth_config()
    providers = oauth_config.list_providers()

    return OAuthProvidersResponse(providers=[OAuthProviderInfo(**p) for p in providers])


@router.get("/{provider}")
async def oauth_authorize(
    provider: str,
    request: Request,
    callback_url: Optional[str] = Query(None, description="登录成功后重定向地址"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    发起 OAuth 授权流程

    重定向用户到 OAuth 提供商的授权页面。

    Args:
        provider: 提供商标识（如 "github", "google"）
        callback_url: 登录成功后重定向地址（可选）
    """
    oauth_service = OAuthService(db)

    # 构建回调 URL
    # 使用 request.url 获取当前 host，确保在代理后也能正常工作
    base_url = str(request.base_url).rstrip("/")

    # 如果有 X-Forwarded-Host 等头，使用它们
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        proto = forwarded_proto or "https"
        base_url = f"{proto}://{forwarded_host}"

    redirect_uri = f"{base_url}/api/v1/auth/oauth/{provider}/callback"

    # 生成 state（包含 callback_url）
    import json
    import secrets

    state = secrets.token_urlsafe(32)

    # 存储 state 数据到 Redis
    from app.core.redis import RedisClient

    state_data = {
        "provider": provider,
        "redirect_uri": redirect_uri,
        "callback_url": callback_url or get_oauth_config().settings.default_redirect_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if RedisClient.is_available():
        try:
            state_key = f"oauth_state:{state}"
            await RedisClient.set(state_key, json.dumps(state_data), expire=600)  # 10 分钟过期
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Failed to store state in Redis: {e}")

    # 生成授权 URL
    try:
        authorization_url, _ = await oauth_service.generate_authorization_url(
            provider_name=provider,
            redirect_uri=redirect_uri,
            state=state,
        )
    except Exception as e:
        logger.error(f"{LOG_PREFIX} Failed to generate authorization URL: {e}")
        raise BadRequestException(f"Failed to initiate OAuth flow: {str(e)}")

    logger.info(f"{LOG_PREFIX} Redirecting to {provider} authorization")
    return RedirectResponse(url=authorization_url, status_code=302)


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(..., description="授权码"),
    state: str = Query(..., description="State 参数"),
    error: Optional[str] = Query(None, description="错误信息"),
    error_description: Optional[str] = Query(None, description="错误描述"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    处理 OAuth 回调

    验证授权、获取用户信息、创建/绑定用户、生成 JWT tokens。

    Args:
        provider: 提供商标识
        code: OAuth 授权码
        state: State 参数
        error: 错误信息（如果用户拒绝授权）
        error_description: 错误描述
    """
    oauth_config = get_oauth_config()
    frontend_url = settings.frontend_url.rstrip("/")

    # 处理用户拒绝授权的情况
    if error:
        logger.warning(f"{LOG_PREFIX} OAuth error: {error} - {error_description}")
        error_url = f"{frontend_url}/signin?error=oauth_denied&error_description={error_description or error}"
        return RedirectResponse(url=error_url, status_code=302)

    # 1. 验证 state
    import json

    from app.core.redis import RedisClient

    state_data = None
    callback_url = oauth_config.settings.default_redirect_url

    if RedisClient.is_available():
        try:
            state_key = f"oauth_state:{state}"
            state_data_str = await RedisClient.get(state_key)
            if state_data_str:
                state_data = json.loads(state_data_str)
                callback_url = state_data.get("callback_url", callback_url)
                # 删除已使用的 state
                await RedisClient.delete(state_key)
            else:
                logger.warning(f"{LOG_PREFIX} Invalid or expired state: {state[:20]}...")
                error_url = f"{frontend_url}/signin?error=invalid_state"
                return RedirectResponse(url=error_url, status_code=302)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Failed to validate state: {e}")

    # 验证 provider 匹配
    if state_data and state_data.get("provider") != provider:
        logger.warning(f"{LOG_PREFIX} Provider mismatch: expected {state_data.get('provider')}, got {provider}")
        error_url = f"{frontend_url}/signin?error=provider_mismatch"
        return RedirectResponse(url=error_url, status_code=302)

    oauth_service = OAuthService(db)

    try:
        # 2. 构建回调 URL
        base_url = str(request.base_url).rstrip("/")
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host:
            proto = forwarded_proto or "https"
            base_url = f"{proto}://{forwarded_host}"
        redirect_uri = f"{base_url}/api/v1/auth/oauth/{provider}/callback"

        # 3. 用授权码换取 tokens
        tokens = await oauth_service.exchange_code_for_tokens(
            provider_name=provider,
            code=code,
            redirect_uri=redirect_uri,
        )

        # 4. 获取用户信息
        access_token = tokens.get("access_token")
        if not access_token:
            raise BadRequestException("No access token in response")

        userinfo = await oauth_service.fetch_userinfo(
            provider_name=provider,
            access_token=access_token,
        )

        # 5. 解析用户信息
        parsed_info = oauth_service.parse_userinfo(provider, userinfo)

        # 6. 查找或创建用户
        user, is_new_user = await oauth_service.find_or_create_user(
            provider_name=provider,
            provider_account_id=parsed_info["provider_id"],
            email=parsed_info.get("email"),
            name=parsed_info.get("name"),
            avatar=parsed_info.get("avatar"),
            tokens=tokens,
            raw_userinfo=userinfo,
        )

        # 7. 提交数据库事务
        await db.commit()
        # 与普通登录一致：更新最后登录、审计、确保个人空间（共享模块）
        ip_address = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        from app.services.login_init import run_post_login_init

        await run_post_login_init(db, user, ip_address)
        # 8. 生成 JWT tokens
        jwt_access_token = create_access_token(
            subject=user.id,
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )
        jwt_refresh_token = generate_refresh_token()
        csrf_token = create_csrf_token(user.id)

        # 存储 refresh token 到 Redis
        if RedisClient.is_available():
            try:
                refresh_expire_seconds = settings.refresh_token_expire_days * 24 * 60 * 60
                await RedisClient.set(
                    f"refresh_token:{jwt_refresh_token}",
                    user.id,
                    expire=refresh_expire_seconds,
                )
                await RedisClient.set(
                    f"account_refresh_token:{user.id}",
                    jwt_refresh_token,
                    expire=refresh_expire_seconds,
                )
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Failed to store refresh token: {e}")

        # 9. 设置 cookies 并重定向
        # 确保 callback_url 是前端 URL
        if not callback_url.startswith("/"):
            callback_url = f"/{callback_url}"
        final_redirect_url = f"{frontend_url}{callback_url}"

        response = RedirectResponse(url=final_redirect_url, status_code=302)

        # 设置 auth cookies
        cookie_kwargs: Dict[str, Any] = {
            "httponly": True,
            "samesite": settings.cookie_samesite,
            "secure": settings.cookie_secure_effective,
            "path": "/",
        }
        if settings.cookie_domain:
            cookie_kwargs["domain"] = settings.cookie_domain

        # Access token cookie
        access_expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
        response.set_cookie(
            key=settings.cookie_name,
            value=jwt_access_token,
            expires=access_expires,
            **cookie_kwargs,
        )

        # Refresh token cookie
        refresh_expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        response.set_cookie(
            key="refresh_token",
            value=jwt_refresh_token,
            expires=refresh_expires,
            **cookie_kwargs,
        )

        # CSRF token cookie (not httponly, needs to be read by JS)
        csrf_cookie_kwargs = {**cookie_kwargs, "httponly": False}
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            expires=access_expires,
            **csrf_cookie_kwargs,
        )

        logger.info(
            f"{LOG_PREFIX} OAuth login successful",
            extra={
                "provider": provider,
                "user_id": user.id,
                "is_new_user": is_new_user,
            },
        )

        return response

    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"{LOG_PREFIX} OAuth callback error: {e}", exc_info=True)
        await db.rollback()
        error_url = f"{frontend_url}/signin?error=oauth_failed&error_description={str(e)}"
        return RedirectResponse(url=error_url, status_code=302)


# ==================== 用户 OAuth 账户管理 ====================


class UserOAuthAccount(BaseModel):
    """用户 OAuth 账户信息"""

    id: str
    provider: str
    provider_account_id: str
    email: Optional[str]
    created_at: datetime


class UserOAuthAccountsResponse(BaseModel):
    """用户 OAuth 账户列表响应"""

    accounts: List[UserOAuthAccount]


@router.get("/accounts/me", response_model=UserOAuthAccountsResponse)
async def get_my_oauth_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserOAuthAccountsResponse:
    """
    获取当前用户的 OAuth 账户绑定列表

    需要用户已登录。
    """
    from app.common.dependencies import get_current_user

    # 手动调用依赖获取当前用户
    current_user = await get_current_user(None, request, db)

    oauth_service = OAuthService(db)
    accounts = await oauth_service.get_user_oauth_accounts(current_user.id)

    return UserOAuthAccountsResponse(
        accounts=[
            UserOAuthAccount(
                id=acc.id,
                provider=acc.provider,
                provider_account_id=acc.provider_account_id,
                email=acc.email,
                created_at=acc.created_at,
            )
            for acc in accounts
        ]
    )


@router.delete("/accounts/{provider}")
async def unlink_oauth_account(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    解绑 OAuth 账户

    需要用户已登录。
    如果用户没有密码且只有一个 OAuth 绑定，不允许解绑。
    """
    from app.common.dependencies import get_current_user

    current_user = await get_current_user(None, request, db)

    oauth_service = OAuthService(db)
    success = await oauth_service.unlink_oauth_account(current_user.id, provider)

    if success:
        await db.commit()

    return {"success": success, "provider": provider}

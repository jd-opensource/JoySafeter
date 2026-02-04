"""
OAuth/OIDC 服务 - 处理 OAuth 登录流程的业务逻辑

功能：
- 生成 OAuth 授权 URL
- 处理 OAuth 回调
- 用授权码换取 tokens
- 获取用户信息
- 查找或创建用户
- 绑定 OAuth 账户
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, cast
from urllib.parse import urlencode

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, UnauthorizedException
from app.core.oauth_config import get_oauth_config
from app.core.redis import RedisClient
from app.models.auth import AuthUser
from app.models.oauth_account import OAuthAccount
from app.repositories.auth_user import AuthUserRepository
from app.services.base import BaseService

LOG_PREFIX = "[OAuthService]"

# State 过期时间（秒）
OAUTH_STATE_EXPIRE_SECONDS = 600  # 10 分钟


class OAuthService(BaseService):
    """OAuth 认证服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.user_repo = AuthUserRepository(db)
        self.oauth_config = get_oauth_config()

    # ==================== 授权流程 ====================

    async def generate_authorization_url(
        self,
        provider_name: str,
        redirect_uri: str,
        state: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        生成 OAuth 授权 URL

        Args:
            provider_name: 提供商标识
            redirect_uri: 回调 URL
            state: 可选的 state 参数，如果不提供则自动生成

        Returns:
            Tuple of (authorization_url, state)

        Raises:
            BadRequestException: 提供商不存在或未启用
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise BadRequestException(f"OAuth provider '{provider_name}' not found or not enabled")

        # 生成或使用提供的 state
        if not state:
            state = secrets.token_urlsafe(32)

        # 存储 state 到 Redis（用于验证回调）
        state_key = f"oauth_state:{state}"
        state_data = {
            "provider": provider_name,
            "redirect_uri": redirect_uri,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if RedisClient.is_available():
            try:
                import json

                await RedisClient.set(state_key, json.dumps(state_data), expire=OAUTH_STATE_EXPIRE_SECONDS)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Failed to store state in Redis: {e}")

        # 获取 authorize URL（可能需要 OIDC Discovery）
        authorize_url: Optional[str] = provider.authorize_url or None
        if not authorize_url and provider.issuer:
            try:
                oidc_config = await self.oauth_config.discover_oidc_config(provider.issuer)
                authorize_url = cast(Optional[str], oidc_config.get("authorization_endpoint"))
            except Exception as e:
                logger.error(f"{LOG_PREFIX} OIDC Discovery failed: {e}")
                raise BadRequestException(f"Failed to discover OAuth endpoints for {provider_name}")

        if not authorize_url:
            raise BadRequestException(f"No authorization URL configured for {provider_name}")

        # 构建授权 URL 参数
        params = {
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": provider.scope,
            "state": state,
        }

        # Google 需要 access_type=offline 来获取 refresh_token
        if provider_name == "google":
            params["access_type"] = "offline"
            params["prompt"] = "consent"

        authorization_url = f"{authorize_url}?{urlencode(params)}"
        logger.info(f"{LOG_PREFIX} Generated authorization URL for {provider_name}")

        return authorization_url, state

    async def validate_state(self, state: str) -> Optional[Dict[str, Any]]:
        """
        验证 OAuth state 参数

        Args:
            state: state 参数值

        Returns:
            State 数据或 None（如果无效）
        """
        state_key = f"oauth_state:{state}"

        if RedisClient.is_available():
            try:
                import json

                state_data_str = await RedisClient.get(state_key)
                if state_data_str:
                    # 删除已使用的 state（防止重放攻击）
                    await RedisClient.delete(state_key)
                    return cast(Dict[str, Any], json.loads(state_data_str))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Failed to validate state from Redis: {e}")

        return None

    # ==================== Token 交换 ====================

    async def exchange_code_for_tokens(
        self,
        provider_name: str,
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """
        用授权码换取 tokens

        Args:
            provider_name: 提供商标识
            code: 授权码
            redirect_uri: 回调 URL

        Returns:
            Token 响应字典
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise BadRequestException(f"OAuth provider '{provider_name}' not found")

        # 获取 token URL
        token_url: Optional[str] = provider.token_url or None
        if not token_url and provider.issuer:
            try:
                oidc_config = await self.oauth_config.discover_oidc_config(provider.issuer)
                token_url = cast(Optional[str], oidc_config.get("token_endpoint"))
            except Exception as e:
                logger.error(f"{LOG_PREFIX} OIDC Discovery failed: {e}")
                raise BadRequestException(f"Failed to discover token endpoint for {provider_name}")

        if not token_url:
            raise BadRequestException(f"No token URL configured for {provider_name}")

        # 构建请求
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }

        headers = {"Accept": "application/json"}

        # GitHub 特殊处理：使用 client_secret_post
        if provider.token_endpoint_auth_method == "client_secret_post":
            # client_id 和 client_secret 已在 data 中
            pass
        else:
            # 默认使用 client_secret_basic（HTTP Basic Auth）
            import base64

            credentials = base64.b64encode(f"{provider.client_id}:{provider.client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
            # 移除 data 中的 client credentials
            del data["client_id"]
            del data["client_secret"]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(token_url, data=data, headers=headers)
                response.raise_for_status()

                # GitHub 可能返回 application/x-www-form-urlencoded
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    tokens: Dict[str, Any] = response.json()
                else:
                    # 解析 URL 编码的响应
                    from urllib.parse import parse_qs

                    parsed = parse_qs(response.text)
                    tokens = {k: v[0] for k, v in parsed.items()}

                logger.info(f"{LOG_PREFIX} Token exchange successful for {provider_name}")
                return tokens

        except httpx.HTTPStatusError as e:
            logger.error(f"{LOG_PREFIX} Token exchange failed: {e.response.text}")
            raise BadRequestException(f"Failed to exchange code for tokens: {e.response.text}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Token exchange error: {e}")
            raise BadRequestException(f"Token exchange failed: {str(e)}")

    # ==================== 用户信息 ====================

    async def fetch_userinfo(
        self,
        provider_name: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """
        获取用户信息

        Args:
            provider_name: 提供商标识
            access_token: Access token

        Returns:
            用户信息字典
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise BadRequestException(f"OAuth provider '{provider_name}' not found")

        # 获取 userinfo URL
        userinfo_url = provider.userinfo_url
        if not userinfo_url and provider.issuer:
            try:
                oidc_config = await self.oauth_config.discover_oidc_config(provider.issuer)
                userinfo_url = oidc_config.get("userinfo_endpoint")
            except Exception as e:
                logger.error(f"{LOG_PREFIX} OIDC Discovery failed: {e}")

        if not userinfo_url:
            raise BadRequestException(f"No userinfo URL configured for {provider_name}")

        headers = {
            "Authorization": f"Bearer {access_token}",
            **provider.userinfo_headers,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(userinfo_url, headers=headers)
                response.raise_for_status()
                userinfo: Dict[str, Any] = response.json()

                # GitHub 特殊处理：需要单独获取邮箱
                if provider_name == "github" and not userinfo.get("email"):
                    email = await self._fetch_github_email(access_token)
                    if email:
                        userinfo["email"] = email

                logger.info(f"{LOG_PREFIX} Fetched userinfo for {provider_name}")
                return userinfo

        except httpx.HTTPStatusError as e:
            logger.error(f"{LOG_PREFIX} Failed to fetch userinfo: {e.response.text}")
            raise BadRequestException(f"Failed to fetch user info: {e.response.text}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Userinfo fetch error: {e}")
            raise BadRequestException(f"Failed to fetch user info: {str(e)}")

    async def _fetch_github_email(self, access_token: str) -> Optional[str]:
        """获取 GitHub 用户的主邮箱"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                response.raise_for_status()
                emails = response.json()

                # 优先返回 primary 且 verified 的邮箱
                for email in emails:
                    if email.get("primary") and email.get("verified"):
                        return cast(Optional[str], email.get("email"))

                # 其次返回任意 verified 的邮箱
                for email in emails:
                    if email.get("verified"):
                        return cast(Optional[str], email.get("email"))

                return None
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Failed to fetch GitHub email: {e}")
            return None

    # ==================== 用户管理 ====================

    def parse_userinfo(
        self,
        provider_name: str,
        userinfo: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        根据 user_mapping 解析用户信息

        Args:
            provider_name: 提供商标识
            userinfo: 原始用户信息

        Returns:
            标准化的用户信息
        """
        provider = self.oauth_config.get_provider(provider_name)
        if not provider:
            raise BadRequestException(f"OAuth provider '{provider_name}' not found")

        mapping = provider.user_mapping

        return {
            "provider_id": str(userinfo.get(mapping.get("id", "sub"), "")),
            "email": userinfo.get(mapping.get("email", "email")),
            "name": userinfo.get(mapping.get("name", "name")),
            "avatar": userinfo.get(mapping.get("avatar", "picture")),
        }

    async def find_or_create_user(
        self,
        provider_name: str,
        provider_account_id: str,
        email: Optional[str],
        name: Optional[str],
        avatar: Optional[str],
        tokens: Dict[str, Any],
        raw_userinfo: Dict[str, Any],
    ) -> Tuple[AuthUser, bool]:
        """
        查找或创建 OAuth 用户

        策略：
        1. 先查找已有的 OAuth 绑定
        2. 如果启用了 auto_link_by_email，按邮箱查找现有用户并绑定
        3. 如果启用了 allow_registration，创建新用户

        Args:
            provider_name: 提供商标识
            provider_account_id: 提供商用户 ID
            email: 用户邮箱
            name: 用户名称
            avatar: 头像 URL
            tokens: OAuth tokens
            raw_userinfo: 原始用户信息

        Returns:
            Tuple of (user, is_new_user)

        Raises:
            UnauthorizedException: 用户不存在且不允许注册
        """
        oauth_settings = self.oauth_config.settings

        # 1. 查找已有的 OAuth 绑定
        oauth_account = await self._get_oauth_account(provider_name, provider_account_id)
        if oauth_account:
            user = await self.user_repo.get_by_id(oauth_account.user_id)
            if user:
                # 更新 OAuth tokens
                await self._update_oauth_account_tokens(oauth_account, tokens)
                logger.info(f"{LOG_PREFIX} Found existing OAuth binding for {provider_name}:{provider_account_id}")
                return user, False
            else:
                # OAuth 绑定存在但用户不存在（数据不一致），删除绑定
                logger.warning(f"{LOG_PREFIX} OAuth account exists but user not found, cleaning up")
                await self._delete_oauth_account(oauth_account)

        # 2. 按邮箱查找现有用户（自动绑定）
        if email and oauth_settings.auto_link_by_email:
            existing_user = await self.user_repo.get_by_email(email)
            if existing_user:
                # 创建 OAuth 绑定
                await self._create_oauth_account(
                    user_id=existing_user.id,
                    provider_name=provider_name,
                    provider_account_id=provider_account_id,
                    email=email,
                    tokens=tokens,
                    raw_userinfo=raw_userinfo,
                )
                logger.info(f"{LOG_PREFIX} Linked OAuth to existing user by email: {email}")
                return existing_user, False

        # 3. 创建新用户
        if not oauth_settings.allow_registration:
            raise UnauthorizedException("Registration via OAuth is not allowed. Please sign up first.")

        if not email:
            raise BadRequestException(
                f"Email is required for registration. Please ensure your {provider_name} account has a verified email."
            )

        # 创建新用户
        import uuid

        new_user = AuthUser(
            id=str(uuid.uuid4()),
            email=email,
            name=name or email.split("@")[0],
            image=avatar,
            hashed_password=None,  # SSO 用户无密码
            email_verified=True,  # OAuth 邮箱视为已验证
            is_active=True,
        )
        self.db.add(new_user)
        await self.db.flush()

        # 创建 OAuth 绑定
        await self._create_oauth_account(
            user_id=new_user.id,
            provider_name=provider_name,
            provider_account_id=provider_account_id,
            email=email,
            tokens=tokens,
            raw_userinfo=raw_userinfo,
        )

        logger.info(f"{LOG_PREFIX} Created new user via OAuth: {email}")
        return new_user, True

    # ==================== OAuth Account 管理 ====================

    async def _get_oauth_account(
        self,
        provider_name: str,
        provider_account_id: str,
    ) -> Optional[OAuthAccount]:
        """查找 OAuth 账户绑定"""
        stmt = select(OAuthAccount).where(
            OAuthAccount.provider == provider_name,
            OAuthAccount.provider_account_id == provider_account_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_oauth_account(
        self,
        user_id: str,
        provider_name: str,
        provider_account_id: str,
        email: Optional[str],
        tokens: Dict[str, Any],
        raw_userinfo: Dict[str, Any],
    ) -> OAuthAccount:
        """创建 OAuth 账户绑定"""
        import uuid

        # 计算 token 过期时间
        expires_in = tokens.get("expires_in")
        token_expires_at = None
        if expires_in:
            token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        oauth_account = OAuthAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider_name,
            provider_account_id=provider_account_id,
            email=email,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_expires_at=token_expires_at,
            raw_userinfo=raw_userinfo,
        )
        self.db.add(oauth_account)
        await self.db.flush()

        logger.info(f"{LOG_PREFIX} Created OAuth account: {provider_name}:{provider_account_id}")
        return oauth_account

    async def _update_oauth_account_tokens(
        self,
        oauth_account: OAuthAccount,
        tokens: Dict[str, Any],
    ) -> None:
        """更新 OAuth 账户的 tokens"""
        if tokens.get("access_token"):
            oauth_account.access_token = tokens["access_token"]

        if tokens.get("refresh_token"):
            oauth_account.refresh_token = tokens["refresh_token"]

        expires_in = tokens.get("expires_in")
        if expires_in:
            oauth_account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        await self.db.flush()

    async def _delete_oauth_account(self, oauth_account: OAuthAccount) -> None:
        """删除 OAuth 账户绑定"""
        await self.db.delete(oauth_account)
        await self.db.flush()

    # ==================== 用户 OAuth 账户查询 ====================

    async def get_user_oauth_accounts(self, user_id: str) -> list[OAuthAccount]:
        """获取用户的所有 OAuth 绑定"""
        stmt = select(OAuthAccount).where(OAuthAccount.user_id == user_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def unlink_oauth_account(
        self,
        user_id: str,
        provider_name: str,
    ) -> bool:
        """
        解绑 OAuth 账户

        Args:
            user_id: 用户 ID
            provider_name: 提供商标识

        Returns:
            是否成功解绑

        Raises:
            BadRequestException: 解绑后用户将无法登录
        """
        # 检查用户是否有密码（确保解绑后仍能登录）
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise BadRequestException("User not found")

        # 获取用户所有 OAuth 绑定
        oauth_accounts = await self.get_user_oauth_accounts(user_id)
        target_account = next(
            (acc for acc in oauth_accounts if acc.provider == provider_name),
            None,
        )

        if not target_account:
            return False

        # 如果用户没有密码且只有一个 OAuth 绑定，不允许解绑
        if not user.hashed_password and len(oauth_accounts) == 1:
            raise BadRequestException("Cannot unlink the only OAuth account. Please set a password first.")

        await self._delete_oauth_account(target_account)
        logger.info(f"{LOG_PREFIX} Unlinked OAuth account: {provider_name} from user {user_id}")
        return True

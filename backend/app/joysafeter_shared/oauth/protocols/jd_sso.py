"""
JD SSA SSO protocol handler.

JD SSA is not standard OAuth2. Flow:
1. User logs in via JD SSA, browser gets sso.jd.com Cookie
2. Read ticket from Cookie during callback
3. Compute MD5 signature with client_secret + timestamp + ticket
4. Call verifyTicket to validate and fetch user info

Reference implementation from autosec:
- autosec/api/libs/oauth.py (JDOAuth)
- autosec/api/controllers/web/oauth_jd.py
"""

import hashlib
import time
from typing import Any, Dict, Optional, cast

import httpx
from fastapi import Request
from loguru import logger

from app.joysafeter_shared.oauth.config import OAuthProviderConfig
from app.joysafeter_shared.oauth.protocols.base import BaseProtocolHandler, UserInfo

LOG_PREFIX = "[JDSSOHandler]"


class JDSSOHandler(BaseProtocolHandler):
    """JD SSA protocol handler."""

    protocol = "jd_sso"

    async def get_user_info(
        self,
        request: Request,
        provider_config: OAuthProviderConfig,
        code: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> UserInfo:
        """
        JD SSO flow: Cookie + verifyTicket

        Args:
            request: FastAPI Request object (reads Cookie)
            provider_config: Provider config
            code: Auth code (not used by JD SSO)
            redirect_uri: Callback URL (not used by JD SSO)

        Returns:
            UserInfo: Unified user info

        Raises:
            ValueError: Failed to fetch user info
        """
        # Fetch user info via Cookie + verifyTicket
        raw_info = await self._verify_ticket(
            request=request,
            client_id=provider_config.client_id,
            client_secret=provider_config.client_secret,
            user_info_url=provider_config.userinfo_url,
        )

        if not raw_info:
            raise ValueError("JD SSO verification failed: missing sso.jd.com cookie or ticket invalid")

        # Parse user info
        return self.parse_user_info(raw_info, provider_config.user_mapping)

    def parse_user_info(
        self,
        raw_info: Dict[str, Any],
        user_mapping: Optional[Dict[str, str]] = None,
    ) -> UserInfo:
        """
        Parse user info returned by JD SSA.

        JD SSA field names differ from standard OAuth2.

        Args:
            raw_info: Raw user info from verifyTicket
            user_mapping: Field mapping config

        Returns:
            UserInfo: Unified user info
        """
        if user_mapping is None:
            user_mapping = {
                "id": "userId",
                "email": "email",
                "name": "username",
                "avatar": "",
            }

        # Provider user ID
        provider_id = str(raw_info.get(user_mapping.get("id", "userId"), ""))

        # Email; fallback to username@jd.com
        email = raw_info.get(user_mapping.get("email", "email"))
        if not email:
            username = raw_info.get("username", "")
            email = f"{username}@jd.com" if username else None

        # Display name
        name = raw_info.get(user_mapping.get("name", "username"), "")
        # If mapped name is empty, fallback to username
        if not name:
            name = raw_info.get("username", "")

        # Avatar (JD typically does not provide)
        avatar_key = user_mapping.get("avatar", "")
        avatar = raw_info.get(avatar_key) if avatar_key else None

        return UserInfo(
            provider_id=provider_id,
            email=email,
            name=name,
            avatar=avatar,
            raw=raw_info,
        )

    async def _verify_ticket(
        self,
        request: Request,
        client_id: str,
        client_secret: str,
        user_info_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Verify JD SSA ticket and fetch user info.

        Args:
            request: FastAPI Request (reads Cookie)
            client_id: JD app ID
            client_secret: JD app secret (for signing)
            user_info_url: verifyTicket endpoint URL

        Returns:
            User info dict; None on failure
        """
        if not user_info_url:
            logger.warning(f"{LOG_PREFIX} Missing user_info_url in provider config")
            return None

        verify_url = user_info_url
        # 1) Read ticket from Cookie
        ticket = request.cookies.get("sso.jd.com")
        if not ticket:
            logger.warning(f"{LOG_PREFIX} Missing sso.jd.com cookie in request")
            return None

        # 2) Compute signature: md5(client_secret + timestamp + ticket)
        timestamp = int(round(time.time() * 1000))
        sign_str = f"{client_secret}{timestamp}{ticket}"
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

        # 3) Get client IP
        client_ip = "unknown"
        if request.client:
            client_ip = request.client.host
        # Prefer X-Forwarded-For (proxy)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # 4) Build request params
        params: Dict[str, str | int] = {
            "ticket": ticket,
            "url": str(request.url),
            "ip": client_ip,
            "app": client_id,
            "time": timestamp,
            "sign": sign,
        }

        logger.debug(f"{LOG_PREFIX} Calling verifyTicket: url={verify_url}, app={client_id}, ip={client_ip}")

        # 5) Call verifyTicket
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(verify_url, params=params)
                response.raise_for_status()
                response_json = response.json()
        except httpx.HTTPError as e:
            logger.error(f"{LOG_PREFIX} HTTP error calling verifyTicket: {e}")
            return None
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Error calling verifyTicket: {e}")
            return None

        # 6) Parse response
        if response_json.get("REQ_FLAG"):
            user_data = response_json.get("REQ_DATA", {})
            logger.info(
                f"{LOG_PREFIX} User info retrieved successfully",
                extra={
                    "username": user_data.get("username"),
                    "userId": user_data.get("userId"),
                },
            )
            return cast(Dict[str, Any], user_data)
        else:
            error_msg = response_json.get("REQ_MSG", "Unknown error")
            logger.error(f"{LOG_PREFIX} verifyTicket failed: {error_msg}, response={response_json}")
            return None

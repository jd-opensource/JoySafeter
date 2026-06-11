"""
Standard OAuth2/OIDC protocol handler.

Implements the OAuth2 authorization code flow:
1. Exchange code for access_token
2. Fetch userinfo with access_token
"""

import base64
from typing import Any, Dict, Optional, cast

import httpx
from fastapi import Request
from loguru import logger

from app.joysafeter_shared.oauth.config import OAuthProviderConfig, get_oauth_config
from app.joysafeter_shared.oauth.protocols.base import BaseProtocolHandler, UserInfo

LOG_PREFIX = "[OAuth2Handler]"


class OAuth2Handler(BaseProtocolHandler):
    """Standard OAuth2/OIDC protocol handler."""

    protocol = "oauth2"

    async def get_user_info(
        self,
        request: Request,
        provider_config: OAuthProviderConfig,
        code: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> UserInfo:
        """
        OAuth2 flow: code → token → userinfo

        Args:
            request: FastAPI Request object
            provider_config: Provider config
            code: Auth code (required)
            redirect_uri: Callback URL (required)

        Returns:
            UserInfo: Unified user info

        Raises:
            ValueError: Missing params or fetch failure
        """
        if not code:
            raise ValueError("Authorization code is required for OAuth2")
        if not redirect_uri:
            raise ValueError("Redirect URI is required for OAuth2")

        # 1) Exchange code for tokens
        tokens = await self._exchange_code_for_tokens(
            provider_config=provider_config,
            code=code,
            redirect_uri=redirect_uri,
        )

        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("No access token in response")

        # 2) Fetch user info
        raw_info = await self._fetch_userinfo(
            provider_config=provider_config,
            access_token=access_token,
        )

        # 3) Parse user info
        return self.parse_user_info(raw_info, provider_config.user_mapping)

    async def _exchange_code_for_tokens(
        self,
        provider_config: OAuthProviderConfig,
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """
        Exchange code for tokens.

        Args:
            provider_config: Provider config
            code: Auth code
            redirect_uri: Callback URL

        Returns:
            Tokens dict containing access_token, etc.
        """
        # Get token URL (may require OIDC Discovery)
        token_url: Optional[str] = provider_config.token_url
        if not token_url and provider_config.issuer:
            oauth_config = get_oauth_config()
            try:
                oidc_config = await oauth_config.discover_oidc_config(provider_config.issuer)
                token_url = cast(Optional[str], oidc_config.get("token_endpoint"))
            except Exception as e:
                logger.error(f"{LOG_PREFIX} OIDC Discovery failed: {e}")
                raise ValueError(f"Failed to discover token endpoint for {provider_config.name}")

        if not token_url:
            raise ValueError(f"No token URL configured for {provider_config.name}")

        # Build request payload
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        # Add credentials based on auth method
        headers: Dict[str, str] = {"Accept": "application/json"}

        if provider_config.token_endpoint_auth_method == "client_secret_post":
            # Pass credentials in request body
            data["client_id"] = provider_config.client_id
            data["client_secret"] = provider_config.client_secret
        else:
            # Default to Basic Auth (client_secret_basic)
            credentials = base64.b64encode(
                f"{provider_config.client_id}:{provider_config.client_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {credentials}"

        # Send request
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, data=data, headers=headers)

            if response.status_code != 200:
                logger.error(f"{LOG_PREFIX} Token exchange failed: {response.status_code} - {response.text}")
                raise ValueError(f"Token exchange failed: {response.status_code}")

            tokens = response.json()
            logger.info(f"{LOG_PREFIX} Token exchange successful for {provider_config.name}")
            return cast(Dict[str, Any], tokens)

    async def _fetch_userinfo(
        self,
        provider_config: OAuthProviderConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """
        Fetch user info.

        Args:
            provider_config: Provider config
            access_token: Access token

        Returns:
            User info dict
        """
        # Get userinfo URL (may require OIDC Discovery)
        userinfo_url = provider_config.userinfo_url
        if not userinfo_url and provider_config.issuer:
            oauth_config = get_oauth_config()
            try:
                oidc_config = await oauth_config.discover_oidc_config(provider_config.issuer)
                userinfo_url = oidc_config.get("userinfo_endpoint")
            except Exception as e:
                logger.error(f"{LOG_PREFIX} OIDC Discovery failed: {e}")

        if not userinfo_url:
            raise ValueError(f"No userinfo URL configured for {provider_config.name}")

        # Build headers
        headers = {
            "Authorization": f"Bearer {access_token}",
            **provider_config.userinfo_headers,
        }

        # Send request
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(userinfo_url, headers=headers)

            if response.status_code != 200:
                logger.error(f"{LOG_PREFIX} Userinfo fetch failed: {response.status_code} - {response.text}")
                raise ValueError(f"Failed to fetch userinfo: {response.status_code}")

            userinfo = response.json()

            # GitHub special case: email may require extra call
            if provider_config.name == "github" and not userinfo.get("email"):
                userinfo["email"] = await self._fetch_github_email(access_token)

            logger.info(f"{LOG_PREFIX} Userinfo fetched for {provider_config.name}")
            return cast(Dict[str, Any], userinfo)

    async def _fetch_github_email(self, access_token: str) -> Optional[str]:
        """
        Get GitHub primary email.

        /user may not return email; request /user/emails instead.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                if response.status_code == 200:
                    emails = response.json()
                    # Find primary email
                    for email in emails:
                        if email.get("primary"):
                            return cast(Optional[str], email.get("email"))
                    # If no primary, return first
                    if emails:
                        return cast(Optional[str], emails[0].get("email"))
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Failed to fetch GitHub email: {e}")
        return None

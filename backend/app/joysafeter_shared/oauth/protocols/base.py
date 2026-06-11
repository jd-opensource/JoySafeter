"""
Base class for OAuth protocol handlers.

Defines the abstract interface; all protocol handlers must inherit this class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Request

from app.joysafeter_shared.oauth.config import OAuthProviderConfig

LOG_PREFIX = "[OAuthProtocol]"


@dataclass
class UserInfo:
    """
    Unified user info structure.

    All protocol handlers should return this structure for consistent handling.
    """

    provider_id: str  # Provider user identifier
    email: Optional[str]  # Email
    name: Optional[str]  # Display name
    avatar: Optional[str]  # Avatar URL
    raw: Dict[str, Any]  # Raw user info (debug/extension)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "provider_id": self.provider_id,
            "email": self.email,
            "name": self.name,
            "avatar": self.avatar,
            "raw": self.raw,
        }


class BaseProtocolHandler(ABC):
    """
    Base class for OAuth protocol handlers.

    Each protocol (oauth2, jd_sso, etc.) must implement these abstract methods.
    """

    # Protocol identifier (override in subclasses)
    protocol: str = "base"

    @abstractmethod
    async def get_user_info(
        self,
        request: Request,
        provider_config: OAuthProviderConfig,
        code: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> UserInfo:
        """
        Fetch user info.

        Different protocols implement different flows:
        - OAuth2: exchange code for token, then userinfo
        - JD SSO: use Cookie + verifyTicket

        Args:
            request: FastAPI Request object
            provider_config: Provider config
            code: Auth code (required for OAuth2; optional otherwise)
            redirect_uri: Callback URL (required for OAuth2)

        Returns:
            UserInfo: Unified user info

        Raises:
            Exception: Failed to fetch user info
        """
        pass

    def parse_user_info(
        self,
        raw_info: Dict[str, Any],
        user_mapping: Optional[Dict[str, str]] = None,
    ) -> UserInfo:
        """
        Parse user info.

        Convert raw user info into unified UserInfo structure.
        Subclasses can override for protocol-specific mapping.

        Args:
            raw_info: Raw user info
            user_mapping: Field mapping config

        Returns:
            UserInfo: Unified user info
        """
        if user_mapping is None:
            user_mapping = {
                "id": "sub",
                "email": "email",
                "name": "name",
                "avatar": "picture",
            }

        # Provider user ID
        provider_id = str(raw_info.get(user_mapping.get("id", "sub"), ""))

        # Email
        email = raw_info.get(user_mapping.get("email", "email"))

        # Display name
        name = raw_info.get(user_mapping.get("name", "name"), "")

        # Avatar
        avatar = raw_info.get(user_mapping.get("avatar", "picture"))

        return UserInfo(
            provider_id=provider_id,
            email=email,
            name=name,
            avatar=avatar,
            raw=raw_info,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} protocol={self.protocol}>"

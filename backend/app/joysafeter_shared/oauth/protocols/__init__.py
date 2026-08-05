"""
OAuth protocol handlers.

Implemented protocols:
- OAuth2Handler: standard OAuth2/OIDC
- JDSSOHandler: JD SSA

Usage:
    from app.joysafeter_shared.oauth.protocols import get_handler

    handler = get_handler("oauth2")  # or "jd_sso"
    user_info = await handler.get_user_info(request, provider_config, code)
"""

from app.joysafeter_shared.oauth.protocols.base import BaseProtocolHandler, UserInfo
from app.joysafeter_shared.oauth.protocols.jd_sso import JDSSOHandler
from app.joysafeter_shared.oauth.protocols.oauth2 import OAuth2Handler

__all__ = [
    "BaseProtocolHandler",
    "UserInfo",
    "OAuth2Handler",
    "JDSSOHandler",
]

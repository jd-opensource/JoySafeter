"""
OAuth/OIDC auth module.

Multi-protocol OAuth framework:
- Standard OAuth2/OIDC (GitHub, Google, Keycloak, etc.)
- JD SSA (JD SSO)
- Extensible for other enterprise SSO protocols

Module layout:
- config.py: config loader (OAuthProviderConfig, OAuthConfigLoader)
- factory.py: protocol handler factory
- protocols/: protocol implementations
  - base.py: abstract base class
  - oauth2.py: standard OAuth2
  - jd_sso.py: JD SSA
"""

from app.joysafeter_shared.oauth.config import (
    OAuthConfigLoader,
    OAuthProviderConfig,
    OAuthSettings,
    get_oauth_config,
    reload_oauth_config,
)
from app.joysafeter_shared.oauth.factory import get_protocol_handler

__all__ = [
    "OAuthConfigLoader",
    "OAuthProviderConfig",
    "OAuthSettings",
    "get_oauth_config",
    "reload_oauth_config",
    "get_protocol_handler",
]

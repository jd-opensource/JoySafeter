from types import MappingProxyType
from typing import Mapping

_PROVIDER_TEMPLATES: dict[str, dict[str, object]] = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
        "user_mapping": {
            "id": "id",
            "email": "email",
            "name": "name",
            "avatar": "avatar_url",
        },
        "token_endpoint_auth_method": "client_secret_post",
        "userinfo_headers": {"Accept": "application/vnd.github+json"},
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "user_mapping": {
            "id": "sub",
            "email": "email",
            "name": "name",
            "avatar": "picture",
        },
    },
    "microsoft": {
        "authorize_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
        "user_mapping": {
            "id": "sub",
            "email": "email",
            "name": "name",
            "avatar": "picture",
        },
        "default_tenant": "common",
    },
    "gitlab": {
        "authorize_url": "https://gitlab.com/oauth/authorize",
        "token_url": "https://gitlab.com/oauth/token",
        "userinfo_url": "https://gitlab.com/api/v4/user",
        "scope": "read_user",
        "user_mapping": {
            "id": "id",
            "email": "email",
            "name": "name",
            "avatar": "avatar_url",
        },
    },
}


PROVIDER_TEMPLATES: Mapping[str, Mapping[str, object]] = MappingProxyType(
    {name: MappingProxyType(dict(values)) for name, values in _PROVIDER_TEMPLATES.items()}
)

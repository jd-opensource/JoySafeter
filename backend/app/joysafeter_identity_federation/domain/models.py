import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeAlias

from app.joysafeter_shared.ids import OAuthAccountId, UserId


class ProtocolId(StrEnum):
    OAUTH2 = "oauth2"
    JD_SSO = "jd_sso"


class LoginMode(StrEnum):
    CHOOSER = "chooser"
    REDIRECT = "redirect"


class CorrelationMethod(StrEnum):
    OAUTH_STATE = "oauth_state"
    SIGNED_COOKIE = "signed_cookie"


@dataclass(frozen=True, slots=True)
class RequestContext:
    base_url: str
    request_url: str
    client_ip: str
    headers: Mapping[str, str]
    cookies: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "cookies", MappingProxyType(dict(self.cookies)))


@dataclass(frozen=True, slots=True)
class CallbackContext(RequestContext):
    query: Mapping[str, str]

    def __post_init__(self) -> None:
        RequestContext.__post_init__(self)
        object.__setattr__(self, "query", MappingProxyType(dict(self.query)))


@dataclass(frozen=True, slots=True)
class CorrelationCookie:
    name: str
    value: str
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class AuthorizationAction:
    authorization_url: str
    correlation_cookie: CorrelationCookie | None = None


@dataclass(frozen=True, slots=True)
class ProviderId:
    value: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.value) is None:
            raise ValueError("ProviderId must be lowercase alphanumeric with optional '-' or '_'")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    id: ProviderId
    display_name: str
    icon: str


def _immutable_mapping(mapping: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(mapping))


def _normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email is not None else None


@dataclass(frozen=True, slots=True)
class OAuth2ProviderSettings:
    client_id: str
    client_secret: str
    authorize_url: str | None
    token_url: str | None
    userinfo_url: str | None
    issuer: str | None
    scope: str
    user_mapping: Mapping[str, str]
    token_endpoint_auth_method: str = "client_secret_basic"
    userinfo_headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_mapping", _immutable_mapping(self.user_mapping))
        object.__setattr__(self, "userinfo_headers", _immutable_mapping(self.userinfo_headers))


@dataclass(frozen=True, slots=True)
class JDSSOProviderSettings:
    client_id: str
    client_secret: str
    authorize_url: str
    userinfo_url: str
    scope: str
    user_mapping: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_mapping", _immutable_mapping(self.user_mapping))


ProviderProtocolSettings: TypeAlias = OAuth2ProviderSettings | JDSSOProviderSettings


@dataclass(frozen=True, slots=True)
class ActiveProvider:
    id: ProviderId
    display_name: str
    icon: str
    protocol: ProtocolId
    settings: ProviderProtocolSettings
    allow_http_loopback: bool = False
    allow_private_network: bool = False


@dataclass(frozen=True, slots=True)
class FederationSettings:
    login_mode: LoginMode
    default_redirect_url: str
    allow_registration: bool
    auto_link_by_email: bool


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    id: str
    provider_id: ProviderId
    callback_url: str
    redirect_uri: str
    correlation_method: CorrelationMethod
    retry_count: int
    created_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True, slots=True)
class FederatedPrincipal:
    provider_id: ProviderId
    subject: str
    email: str | None
    email_verified: bool
    display_name: str | None
    avatar_url: str | None
    claims: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("FederatedPrincipal subject must not be empty")
        object.__setattr__(self, "email", _normalize_email(self.email))
        object.__setattr__(self, "claims", _immutable_mapping(self.claims))


@dataclass(frozen=True, slots=True)
class Authenticated:
    principal: FederatedPrincipal


@dataclass(frozen=True, slots=True)
class RestartAuthorization:
    reason: str


@dataclass(frozen=True, slots=True)
class FederatedUser:
    user_id: UserId
    email: str | None
    is_new_user: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", _normalize_email(self.email))


@dataclass(frozen=True, slots=True)
class FederatedAccountView:
    id: OAuthAccountId
    provider_id: ProviderId
    subject: str
    email: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("FederatedAccountView subject must not be empty")
        object.__setattr__(self, "email", _normalize_email(self.email))


@dataclass(frozen=True, slots=True)
class IssuedAuthSession:
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

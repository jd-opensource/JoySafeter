from dataclasses import dataclass
from datetime import datetime

from ..domain.models import AuthorizationAction, CorrelationCookie


@dataclass(frozen=True, slots=True)
class BeginLoginResult:
    authorization_url: str
    correlation_cookie: CorrelationCookie | None = None


@dataclass(frozen=True, slots=True)
class LoginSucceeded:
    callback_url: str
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


@dataclass(frozen=True, slots=True)
class LoginRestarted:
    authorization_action: AuthorizationAction
    clear_correlation_cookie: bool

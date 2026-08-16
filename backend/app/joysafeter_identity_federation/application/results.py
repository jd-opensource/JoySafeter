from dataclasses import dataclass
from datetime import datetime

from ..domain.errors import FederationError
from ..domain.models import AuthorizationAction, CorrelationCookie
from .callback_policy import CallbackUrlPolicy


@dataclass(frozen=True, slots=True)
class BeginLoginResult:
    authorization_url: str
    state: str
    correlation_cookie: CorrelationCookie | None = None


@dataclass(frozen=True, slots=True)
class LoginSucceeded:
    callback_url: str
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

    @property
    def redirect_path(self) -> str:
        try:
            return CallbackUrlPolicy.validate(self.callback_url)
        except FederationError as error:
            raise FederationError(
                code="FEDERATION_CALLBACK_FAILED",
                message="Federation callback result is invalid",
            ) from error


@dataclass(frozen=True, slots=True)
class LoginRestarted:
    authorization_action: AuthorizationAction
    clear_correlation_cookie: bool

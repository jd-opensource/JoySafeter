from dataclasses import dataclass

from ..domain.models import CorrelationCookie


@dataclass(frozen=True, slots=True)
class BeginLoginResult:
    authorization_url: str
    correlation_cookie: CorrelationCookie | None = None

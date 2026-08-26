from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.repositories.joysafeter_auth_user import AuthUserRepository
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService, run_post_login_init
from app.joysafeter_shared.ids import UserId

from ..domain.errors import FederationError
from ..domain.models import IssuedAuthSession


def _required_token(token_result: object, field: str) -> str:
    value = getattr(token_result, field)
    if not isinstance(value, str) or not value:
        raise TypeError(f"{field} must be a non-empty string")
    return value


def _required_expiry(token_result: object, field: str) -> datetime:
    value = getattr(token_result, field)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{field} must be a timezone-aware datetime")
    return value


def _session_issue_failed() -> FederationError:
    return FederationError(
        code="FEDERATION_SESSION_ISSUE_FAILED",
        message="Unable to issue federated session",
    )


class JoySafeterAuthSessionGateway:
    def __init__(self, db_session: AsyncSession, user_loader: AuthUserRepository | None = None) -> None:
        self._db_session = db_session
        self._users = user_loader or AuthUserRepository(db_session)

    async def issue(self, user_id: UserId, ip_address: str) -> IssuedAuthSession:
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise FederationError(
                code="FEDERATION_PRINCIPAL_INVALID",
                message="Federated principal is invalid",
            )

        await run_post_login_init(self._db_session, user, ip_address)
        try:
            token_result = await AuthService(self._db_session).issue_login_tokens(user)
            return IssuedAuthSession(
                access_token=_required_token(token_result, "access_token"),
                refresh_token=_required_token(token_result, "refresh_token"),
                csrf_token=_required_token(token_result, "csrf_token"),
                access_expires_at=_required_expiry(token_result, "access_expires_at"),
                refresh_expires_at=_required_expiry(token_result, "refresh_expires_at"),
            )
        except (AttributeError, TypeError):
            raise _session_issue_failed() from None

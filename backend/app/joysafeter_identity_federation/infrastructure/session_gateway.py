from collections.abc import Mapping
from datetime import datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.repositories.joysafeter_auth_user import AuthUserRepository
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService, run_post_login_init

from ..domain.errors import FederationError
from ..domain.models import IssuedAuthSession


class JoySafeterAuthSessionGateway:
    def __init__(self, db_session: AsyncSession, user_loader: AuthUserRepository | None = None) -> None:
        self._db_session = db_session
        self._users = user_loader or AuthUserRepository(db_session)

    async def issue(self, user_id: str, ip_address: str) -> IssuedAuthSession:
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise FederationError(
                code="FEDERATION_PRINCIPAL_INVALID",
                message="Federated principal is invalid",
            )

        await run_post_login_init(self._db_session, user, ip_address)
        token_result = cast(Mapping[str, object], await AuthService(self._db_session).issue_login_tokens(user))
        return IssuedAuthSession(
            access_token=cast(str, token_result["access_token"]),
            refresh_token=cast(str, token_result["refresh_token"]),
            csrf_token=cast(str, token_result["csrf_token"]),
            access_expires_at=cast(datetime, token_result["access_expires_at"]),
            refresh_expires_at=cast(datetime, token_result["refresh_expires_at"]),
        )

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_oauth_account import OAuthAccount
from app.joysafeter_domain.repositories.joysafeter_auth_user import AuthUserRepository
from app.joysafeter_shared.ids import OAuthAccountId, UserId

from ..domain.errors import FederationError
from ..domain.models import FederatedAccountView, FederatedPrincipal, FederatedUser, ProviderId
from ..domain.policies import AccountLinkPolicy

_SENSITIVE_CLAIM_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "code",
    "ticket",
    "cookie",
    "cookies",
}


class SqlAlchemyFederatedAccountGateway:
    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session
        self._users = AuthUserRepository(db_session)

    async def resolve_or_create(
        self,
        principal: FederatedPrincipal,
        policy: AccountLinkPolicy,
    ) -> FederatedUser:
        existing_binding = await self._find_subject_binding(principal)
        if existing_binding is not None:
            return await self._resolved_binding(existing_binding)

        existing_user = await self._find_user_by_email(principal.email)
        if existing_user is not None:
            policy.require_auto_link_allowed(
                principal.email,
                principal.email_verified,
                existing_user.email,
                existing_user.is_active,
            )
            return await self._create_binding_with_race_recovery(
                existing_user,
                principal,
                is_new_user=False,
            )

        if not policy.allow_registration:
            raise FederationError(
                code="FEDERATION_REGISTRATION_DISABLED",
                message="Federated registration is disabled",
            )
        if principal.email is None:
            raise FederationError(
                code="FEDERATION_EMAIL_REQUIRED",
                message="An email address is required for federated registration",
            )

        new_user = AuthUser(
            id=UserId.new(),
            email=principal.email,
            name=principal.display_name or principal.email.split("@")[0],
            image=principal.avatar_url,
            hashed_password=None,
            email_verified=principal.email_verified,
            is_active=True,
        )
        return await self._create_binding_with_race_recovery(
            new_user,
            principal,
            is_new_user=True,
        )

    async def list_accounts(self, user_id: UserId) -> tuple[FederatedAccountView, ...]:
        result = await self._db_session.execute(
            select(OAuthAccount)
            .where(OAuthAccount.user_id == user_id)
            .order_by(OAuthAccount.created_at, OAuthAccount.id)
        )
        return tuple(self._account_view(account) for account in result.scalars())

    async def unlink(self, user_id: UserId, provider_id: ProviderId) -> bool:
        user_result = await self._db_session.execute(select(AuthUser).where(AuthUser.id == user_id).with_for_update())
        user = user_result.scalar_one_or_none()
        if user is None:
            raise FederationError(
                code="FEDERATION_USER_NOT_FOUND",
                message="Federated account user was not found",
            )

        accounts_result = await self._db_session.execute(
            select(OAuthAccount).where(OAuthAccount.user_id == user_id).order_by(OAuthAccount.id)
        )
        accounts = tuple(accounts_result.scalars())
        target = next((account for account in accounts if account.provider == provider_id.value), None)
        if target is None:
            return False
        if not user.hashed_password and len(accounts) == 1:
            raise FederationError(
                code="FEDERATION_LAST_ACCOUNT_UNLINK_FORBIDDEN",
                message="The only federated login method cannot be unlinked",
            )

        await self._db_session.delete(target)
        await self._db_session.flush()
        return True

    async def _create_binding_with_race_recovery(
        self,
        user: AuthUser,
        principal: FederatedPrincipal,
        *,
        is_new_user: bool,
    ) -> FederatedUser:
        try:
            async with self._db_session.begin_nested():
                if is_new_user:
                    self._db_session.add(user)
                    await self._db_session.flush()
                binding = self._new_binding(user.id, principal)
                self._db_session.add(binding)
                await self._flush_new_binding(binding)
        except IntegrityError:
            winning_binding = await self._find_subject_binding(principal)
            if winning_binding is not None:
                return await self._resolved_binding(winning_binding)
            if principal.email is not None and await self._find_user_by_email(principal.email) is not None:
                raise FederationError(
                    code="FEDERATION_ACCOUNT_LINK_REQUIRED",
                    message="Federated account requires explicit account linking",
                ) from None
            raise

        return FederatedUser(user_id=user.id, email=user.email, is_new_user=is_new_user)

    async def _find_subject_binding(self, principal: FederatedPrincipal) -> OAuthAccount | None:
        result = await self._db_session.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == principal.provider_id.value,
                OAuthAccount.provider_account_id == principal.subject,
            )
        )
        return result.scalar_one_or_none()

    async def _find_user_by_email(self, email: str | None) -> AuthUser | None:
        if email is None:
            return None
        result = await self._db_session.execute(
            select(AuthUser)
            .where(func.lower(func.btrim(AuthUser.email)) == email.strip().lower())
            .order_by(AuthUser.id)
            .limit(2)
        )
        users = tuple(result.scalars())
        if len(users) > 1:
            raise FederationError(
                code="FEDERATION_ACCOUNT_LINK_REQUIRED",
                message="Federated account requires explicit account linking",
            )
        return users[0] if users else None

    async def _resolved_binding(self, binding: OAuthAccount) -> FederatedUser:
        user = await self._users.get_by_id(binding.user_id)
        if user is None:
            raise FederationError(
                code="FEDERATION_BINDING_USER_NOT_FOUND",
                message="Federated account binding has no user",
            )
        return FederatedUser(user_id=user.id, email=user.email, is_new_user=False)

    async def _flush_new_binding(self, binding: OAuthAccount) -> None:
        await self._db_session.flush()

    @staticmethod
    def _new_binding(user_id: UserId, principal: FederatedPrincipal) -> OAuthAccount:
        return OAuthAccount(
            id=OAuthAccountId.new(),
            user_id=user_id,
            provider=principal.provider_id.value,
            provider_account_id=principal.subject,
            email=principal.email,
            access_token=None,
            refresh_token=None,
            token_expires_at=None,
            raw_userinfo=_sanitize_claims(principal.claims),
        )

    @staticmethod
    def _account_view(account: OAuthAccount) -> FederatedAccountView:
        return FederatedAccountView(
            id=account.id,
            provider_id=ProviderId(account.provider),
            subject=account.provider_account_id,
            email=account.email,
            created_at=account.created_at,
        )


def _sanitize_claims(claims: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _sanitize_claim_value(value) for key, value in claims.items() if key.lower() not in _SENSITIVE_CLAIM_KEYS
    }


def _sanitize_claim_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _sanitize_claims(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_claim_value(item) for item in value]
    return value

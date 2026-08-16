import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..domain.errors import FederationError
from ..domain.models import (
    ActiveProvider,
    CallbackContext,
    LoginAttempt,
    ProviderId,
    RequestContext,
    RestartAuthorization,
)
from ..domain.policies import AccountLinkPolicy
from ..domain.ports import (
    AuthSessionGateway,
    FederatedAccountGateway,
    LoginAttemptStore,
    ProtocolAdapter,
    ProtocolAdapterResolver,
    ProviderRegistryPort,
)
from .callback_policy import CallbackUrlPolicy
from .commands import BeginLoginCommand, CompleteLoginCommand
from .results import BeginLoginResult, LoginRestarted, LoginSucceeded

_ATTEMPT_TTL = timedelta(seconds=600)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FederatedLoginCoordinator:
    def __init__(
        self,
        *,
        registry: ProviderRegistryPort,
        adapters: ProtocolAdapterResolver,
        attempt_store: LoginAttemptStore,
        account_gateway: FederatedAccountGateway | None = None,
        session_gateway: AuthSessionGateway | None = None,
        attempt_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._registry = registry
        self._adapters = adapters
        self._attempt_store = attempt_store
        self._account_gateway = account_gateway
        self._session_gateway = session_gateway
        self._attempt_id_factory = attempt_id_factory or (lambda: secrets.token_urlsafe(32))
        self._clock = clock
        self._callback_policy = CallbackUrlPolicy(registry.settings.default_redirect_url)

    async def begin_login(self, command: BeginLoginCommand, context: RequestContext) -> BeginLoginResult:
        provider_id = self._parse_provider_id(command.provider_id)
        provider = self._registry.require(provider_id)
        callback_url = self._callback_policy.resolve(command.callback_url)
        adapter = self._adapters.require(provider.protocol)
        created_at = self._clock()
        attempt = LoginAttempt(
            id=self._attempt_id_factory(),
            provider_id=provider.id,
            callback_url=callback_url,
            redirect_uri=self._redirect_uri(context, provider.id),
            correlation_method=adapter.correlation_method,
            retry_count=0,
            created_at=created_at,
            expires_at=created_at + _ATTEMPT_TTL,
        )

        action = await adapter.begin_login(provider, attempt, context)
        await self._attempt_store.create(attempt)
        return BeginLoginResult(
            authorization_url=action.authorization_url,
            state=attempt.id,
            correlation_cookie=action.correlation_cookie,
        )

    async def complete_login(
        self,
        command: CompleteLoginCommand,
        context: CallbackContext,
    ) -> LoginSucceeded | LoginRestarted:
        provider_id = self._parse_provider_id(command.provider_id)
        provider = self._registry.require(provider_id)
        adapter = self._adapters.require(provider.protocol)
        account_gateway = self._require_account_gateway()
        session_gateway = self._require_session_gateway()
        attempt_id = adapter.extract_attempt_id(context)
        attempt = await self._attempt_store.consume(attempt_id)
        if attempt is None:
            raise FederationError(
                code="FEDERATION_ATTEMPT_INVALID",
                message="Federation login attempt is invalid",
            )
        if (
            attempt.provider_id != provider.id
            or attempt.redirect_uri != self._redirect_uri(context, provider.id)
            or attempt.correlation_method != adapter.correlation_method
        ):
            raise FederationError(
                code="FEDERATION_ATTEMPT_MISMATCH",
                message="Federation login attempt does not match the provider",
            )
        if attempt.is_expired(self._clock()):
            raise FederationError(
                code="FEDERATION_ATTEMPT_EXPIRED",
                message="Federation login attempt has expired",
            )

        outcome = await adapter.complete_login(provider, attempt, context)
        if isinstance(outcome, RestartAuthorization):
            return await self._restart_login(provider, adapter, attempt, context)

        user = await account_gateway.resolve_or_create(
            outcome.principal,
            AccountLinkPolicy(
                allow_registration=self._registry.settings.allow_registration,
                auto_link_by_email=self._registry.settings.auto_link_by_email,
            ),
        )
        session = await session_gateway.issue(user.user_id, context.client_ip)
        return LoginSucceeded(
            callback_url=attempt.callback_url,
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            csrf_token=session.csrf_token,
            access_expires_at=session.access_expires_at,
            refresh_expires_at=session.refresh_expires_at,
        )

    async def _restart_login(
        self,
        provider: ActiveProvider,
        adapter: ProtocolAdapter,
        consumed: LoginAttempt,
        context: CallbackContext,
    ) -> LoginRestarted:
        if consumed.retry_count >= 1:
            raise FederationError(
                code="FEDERATION_RETRY_EXHAUSTED",
                message="Federation login retry has been exhausted",
            )

        created_at = self._clock()
        replacement = LoginAttempt(
            id=self._attempt_id_factory(),
            provider_id=consumed.provider_id,
            callback_url=consumed.callback_url,
            redirect_uri=consumed.redirect_uri,
            correlation_method=consumed.correlation_method,
            retry_count=consumed.retry_count + 1,
            created_at=created_at,
            expires_at=created_at + _ATTEMPT_TTL,
        )
        action = await adapter.begin_login(provider, replacement, context)
        await self._attempt_store.replace_for_retry(consumed, replacement)
        return LoginRestarted(
            authorization_action=action,
            clear_correlation_cookie=True,
        )

    def _require_account_gateway(self) -> FederatedAccountGateway:
        if self._account_gateway is None:
            raise RuntimeError("Federated account gateway is not configured")
        return self._account_gateway

    def _require_session_gateway(self) -> AuthSessionGateway:
        if self._session_gateway is None:
            raise RuntimeError("Auth session gateway is not configured")
        return self._session_gateway

    @staticmethod
    def _parse_provider_id(value: str) -> ProviderId:
        try:
            return ProviderId(value)
        except ValueError as error:
            raise FederationError(
                code="FEDERATION_PROVIDER_NOT_ACTIVE",
                message=f"Provider {value!r} is not active",
            ) from error

    @staticmethod
    def _redirect_uri(context: RequestContext, provider_id: ProviderId) -> str:
        base_url = context.base_url.rstrip("/")
        return f"{base_url}/api/v1/auth/oauth/{provider_id.value}/callback"

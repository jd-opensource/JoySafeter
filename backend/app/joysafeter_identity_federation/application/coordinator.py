import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..domain.errors import FederationError
from ..domain.models import LoginAttempt, ProviderId, RequestContext
from ..domain.ports import LoginAttemptStore, ProtocolAdapterResolver, ProviderRegistryPort
from .callback_policy import CallbackUrlPolicy
from .commands import BeginLoginCommand
from .results import BeginLoginResult

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
        attempt_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._registry = registry
        self._adapters = adapters
        self._attempt_store = attempt_store
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
            correlation_cookie=action.correlation_cookie,
        )

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

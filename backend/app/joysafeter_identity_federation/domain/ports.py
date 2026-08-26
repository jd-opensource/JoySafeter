from typing import Protocol

from app.joysafeter_shared.ids import UserId

from .models import (
    ActiveProvider,
    Authenticated,
    AuthorizationAction,
    CallbackContext,
    CorrelationMethod,
    FederatedAccountView,
    FederatedPrincipal,
    FederatedUser,
    FederationSettings,
    IssuedAuthSession,
    LoginAttempt,
    ProtocolId,
    ProviderDescriptor,
    ProviderId,
    RequestContext,
    RestartAuthorization,
)
from .policies import AccountLinkPolicy


class ProviderRegistryPort(Protocol):
    settings: FederationSettings

    def require(self, provider_id: ProviderId) -> ActiveProvider: ...

    def list_public(self) -> tuple[ProviderDescriptor, ...]: ...


class ProtocolAdapter(Protocol):
    protocol_id: ProtocolId
    correlation_method: CorrelationMethod

    def extract_attempt_id(self, context: CallbackContext) -> str: ...

    async def begin_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: RequestContext,
    ) -> AuthorizationAction: ...

    async def complete_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: CallbackContext,
    ) -> Authenticated | RestartAuthorization: ...


class ProtocolAdapterResolver(Protocol):
    def require(self, protocol_id: ProtocolId) -> ProtocolAdapter: ...


class LoginAttemptStore(Protocol):
    async def create(self, attempt: LoginAttempt) -> None: ...

    async def consume(self, attempt_id: str) -> LoginAttempt | None: ...

    async def replace_for_retry(self, consumed: LoginAttempt, replacement: LoginAttempt) -> None: ...


class FederatedAccountGateway(Protocol):
    async def resolve_or_create(
        self,
        principal: FederatedPrincipal,
        policy: AccountLinkPolicy,
    ) -> FederatedUser: ...

    async def list_accounts(self, user_id: UserId) -> tuple[FederatedAccountView, ...]: ...

    async def unlink(self, user_id: UserId, provider_id: ProviderId) -> bool: ...


class AuthSessionGateway(Protocol):
    async def issue(self, user_id: UserId, ip_address: str) -> IssuedAuthSession: ...

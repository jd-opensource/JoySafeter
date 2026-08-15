import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.joysafeter_identity_federation.application.commands import BeginLoginCommand
from app.joysafeter_identity_federation.application.coordinator import FederatedLoginCoordinator
from app.joysafeter_identity_federation.application.results import BeginLoginResult
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    ActiveProvider,
    AuthorizationAction,
    CallbackContext,
    CorrelationCookie,
    CorrelationMethod,
    FederationSettings,
    LoginAttempt,
    LoginMode,
    OAuth2ProviderSettings,
    ProtocolId,
    ProviderId,
    RequestContext,
)
from app.joysafeter_identity_federation.infrastructure.registry import ProviderRegistry

pytestmark = pytest.mark.no_db

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


class _RecordingAdapter:
    protocol_id = ProtocolId.OAUTH2
    correlation_method = CorrelationMethod.OAUTH_STATE

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[ActiveProvider, LoginAttempt, RequestContext]] = []
        self.error = error
        self.cookie = CorrelationCookie(
            name="joysafeter_federation_attempt",
            value="signed-attempt",
            max_age_seconds=600,
        )

    def extract_attempt_id(self, context: CallbackContext) -> str:
        raise AssertionError(f"unexpected callback extraction: {context}")

    async def begin_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: RequestContext,
    ) -> AuthorizationAction:
        self.calls.append((provider, attempt, context))
        if self.error is not None:
            raise self.error
        return AuthorizationAction(
            authorization_url=f"https://provider.example/authorize?state={attempt.id}",
            correlation_cookie=self.cookie,
        )

    async def complete_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: CallbackContext,
    ) -> object:
        raise AssertionError(f"unexpected callback completion: {provider}, {attempt}, {context}")


class _RecordingAdapterResolver:
    def __init__(self, adapter: _RecordingAdapter) -> None:
        self.adapter = adapter
        self.required: list[ProtocolId] = []

    def require(self, protocol_id: ProtocolId) -> _RecordingAdapter:
        self.required.append(protocol_id)
        return self.adapter


class _RecordingAttemptStore:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.created: list[LoginAttempt] = []
        self.error = error

    async def create(self, attempt: LoginAttempt) -> None:
        self.created.append(attempt)
        if self.error is not None:
            raise self.error

    async def consume(self, attempt_id: str) -> LoginAttempt | None:
        raise AssertionError(f"unexpected attempt consumption: {attempt_id}")

    async def replace_for_retry(self, consumed: LoginAttempt, replacement: LoginAttempt) -> None:
        raise AssertionError(f"unexpected attempt replacement: {consumed}, {replacement}")


def _provider() -> ActiveProvider:
    return ActiveProvider(
        id=ProviderId("github"),
        display_name="GitHub",
        icon="github",
        protocol=ProtocolId.OAUTH2,
        settings=OAuth2ProviderSettings(
            client_id="client-id",
            client_secret="client-secret",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            issuer=None,
            scope="read:user user:email",
            user_mapping={"id": "id"},
        ),
    )


def _registry(*, default_redirect_url: str = "/managed/quickstart") -> ProviderRegistry:
    return ProviderRegistry(
        [_provider()],
        FederationSettings(
            login_mode=LoginMode.CHOOSER,
            default_redirect_url=default_redirect_url,
            allow_registration=True,
            auto_link_by_email=True,
        ),
    )


def _request_context(*, base_url: str = "https://api.example.com") -> RequestContext:
    return RequestContext(
        base_url=base_url,
        request_url=f"{base_url.rstrip('/')}/api/v1/auth/oauth/github",
        client_ip="203.0.113.10",
        headers={"host": "api.example.com"},
        cookies={},
    )


def _coordinator(
    *,
    store: _RecordingAttemptStore | None = None,
    adapter: _RecordingAdapter | None = None,
    attempt_ids: Iterator[str] | None = None,
    default_redirect_url: str = "/managed/quickstart",
    clock: Callable[[], datetime] = lambda: _NOW,
) -> tuple[FederatedLoginCoordinator, _RecordingAttemptStore, _RecordingAdapter, _RecordingAdapterResolver]:
    resolved_store = store or _RecordingAttemptStore()
    resolved_adapter = adapter or _RecordingAdapter()
    adapters = _RecordingAdapterResolver(resolved_adapter)
    coordinator = FederatedLoginCoordinator(
        registry=_registry(default_redirect_url=default_redirect_url),
        adapters=adapters,
        attempt_store=resolved_store,
        attempt_id_factory=(lambda: next(attempt_ids)) if attempt_ids is not None else None,
        clock=clock,
    )
    return coordinator, resolved_store, resolved_adapter, adapters


@pytest.mark.asyncio
async def test_begin_login_creates_one_attempt_and_delegates_once() -> None:
    coordinator, store, adapter, adapters = _coordinator(attempt_ids=iter(["attempt-1"]))
    context = _request_context(base_url="https://api.example.com/")

    result = await coordinator.begin_login(
        BeginLoginCommand(provider_id="github", callback_url="/managed/dashboard"),
        context,
    )

    assert result == BeginLoginResult(
        authorization_url="https://provider.example/authorize?state=attempt-1",
        correlation_cookie=adapter.cookie,
    )
    assert adapters.required == [ProtocolId.OAUTH2]
    assert len(adapter.calls) == 1
    assert len(store.created) == 1
    provider, delegated_attempt, delegated_context = adapter.calls[0]
    assert provider.id == ProviderId("github")
    assert delegated_context is context
    assert delegated_attempt is store.created[0]
    assert delegated_attempt == LoginAttempt(
        id="attempt-1",
        provider_id=ProviderId("github"),
        callback_url="/managed/dashboard",
        redirect_uri="https://api.example.com/api/v1/auth/oauth/github/callback",
        correlation_method=CorrelationMethod.OAUTH_STATE,
        retry_count=0,
        created_at=_NOW,
        expires_at=_NOW + timedelta(seconds=600),
    )


@pytest.mark.asyncio
async def test_begin_login_uses_compiled_default_only_when_callback_is_absent() -> None:
    coordinator, store, _, _ = _coordinator(attempt_ids=iter(["attempt-1"]))

    await coordinator.begin_login(BeginLoginCommand(provider_id="github", callback_url=None), _request_context())

    assert store.created[0].callback_url == "/managed/quickstart"


@pytest.mark.parametrize(
    "callback_url",
    [
        "",
        " ",
        "managed/dashboard",
        "https://evil.example/steal",
        "http://evil.example/steal",
        "//evil.example/path",
        "///evil.example/path",
        "\\evil.example/path",
        "/managed\\evil",
        "/managed\nnext",
        "/managed\rnext",
        "/managed\tnext",
        "/managed\x00next",
        "/managed path",
        "/%2f%2fevil.example/path",
        "/%5cevil.example/path",
        "/%00evil.example/path",
        "/%GG",
        "/../admin",
        "/%2e%2e/admin",
        "/\ud800",
    ],
)
@pytest.mark.asyncio
async def test_begin_login_rejects_invalid_or_ambiguous_callback_urls(callback_url: str) -> None:
    coordinator, store, adapter, adapters = _coordinator(attempt_ids=iter(["attempt-1"]))

    with pytest.raises(FederationError) as exc_info:
        await coordinator.begin_login(
            BeginLoginCommand(provider_id="github", callback_url=callback_url),
            _request_context(),
        )

    assert exc_info.value.code == "FEDERATION_CALLBACK_URL_INVALID"
    assert adapters.required == []
    assert adapter.calls == []
    assert store.created == []


@pytest.mark.asyncio
async def test_begin_login_preserves_valid_relative_query_and_fragment() -> None:
    coordinator, store, _, _ = _coordinator(attempt_ids=iter(["attempt-1"]))
    callback_url = "/managed/dashboard?tab=activity#recent"

    await coordinator.begin_login(
        BeginLoginCommand(provider_id="github", callback_url=callback_url),
        _request_context(),
    )

    assert store.created[0].callback_url == callback_url


@pytest.mark.parametrize("provider_id", ["google", "../github"])
@pytest.mark.asyncio
async def test_begin_login_requires_an_active_valid_provider_before_delegation(provider_id: str) -> None:
    coordinator, store, adapter, adapters = _coordinator(attempt_ids=iter(["attempt-1"]))

    with pytest.raises(FederationError) as exc_info:
        await coordinator.begin_login(
            BeginLoginCommand(provider_id=provider_id, callback_url="/managed/dashboard"),
            _request_context(),
        )

    assert exc_info.value.code == "FEDERATION_PROVIDER_NOT_ACTIVE"
    assert adapters.required == []
    assert adapter.calls == []
    assert store.created == []


@pytest.mark.asyncio
async def test_begin_login_does_not_persist_when_adapter_fails() -> None:
    adapter_error = FederationError(
        code="FEDERATION_UPSTREAM_UNAVAILABLE",
        message="Provider is unavailable",
        retryable=True,
    )
    adapter = _RecordingAdapter(error=adapter_error)
    coordinator, store, _, _ = _coordinator(adapter=adapter, attempt_ids=iter(["attempt-1"]))

    with pytest.raises(FederationError) as exc_info:
        await coordinator.begin_login(
            BeginLoginCommand(provider_id="github", callback_url="/managed/dashboard"),
            _request_context(),
        )

    assert exc_info.value is adapter_error
    assert len(adapter.calls) == 1
    assert store.created == []


@pytest.mark.asyncio
async def test_begin_login_delegates_once_when_attempt_persistence_fails() -> None:
    store_error = FederationError(
        code="FEDERATION_STATE_STORE_UNAVAILABLE",
        message="Federation login state is unavailable",
        retryable=True,
    )
    store = _RecordingAttemptStore(error=store_error)
    coordinator, _, adapter, _ = _coordinator(store=store, attempt_ids=iter(["attempt-1"]))

    with pytest.raises(FederationError) as exc_info:
        await coordinator.begin_login(
            BeginLoginCommand(provider_id="github", callback_url="/managed/dashboard"),
            _request_context(),
        )

    assert exc_info.value is store_error
    assert len(adapter.calls) == 1
    assert len(store.created) == 1


@pytest.mark.asyncio
async def test_default_attempt_id_contains_256_bits_of_url_safe_randomness() -> None:
    coordinator, store, _, _ = _coordinator()

    await coordinator.begin_login(
        BeginLoginCommand(provider_id="github", callback_url="/managed/dashboard"),
        _request_context(),
    )

    attempt_id = store.created[0].id
    decoded = base64.urlsafe_b64decode(f"{attempt_id}=")
    assert len(decoded) == 32
    assert "+" not in attempt_id
    assert "/" not in attempt_id
    assert "=" not in attempt_id

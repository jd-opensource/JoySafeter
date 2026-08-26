from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.joysafeter_identity_federation.application.commands import CompleteLoginCommand
from app.joysafeter_identity_federation.application.coordinator import FederatedLoginCoordinator
from app.joysafeter_identity_federation.application.results import LoginRestarted, LoginSucceeded
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import (
    ActiveProvider,
    Authenticated,
    AuthorizationAction,
    CallbackContext,
    CorrelationCookie,
    CorrelationMethod,
    FederatedPrincipal,
    FederatedUser,
    FederationSettings,
    IssuedAuthSession,
    JDSSOProviderSettings,
    LoginAttempt,
    LoginMode,
    OAuth2ProviderSettings,
    ProtocolId,
    ProviderId,
    RequestContext,
    RestartAuthorization,
)
from app.joysafeter_identity_federation.domain.policies import AccountLinkPolicy
from app.joysafeter_identity_federation.infrastructure.registry import ProviderRegistry
from app.joysafeter_shared.ids import UserId

pytestmark = pytest.mark.no_db

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_ACCESS_EXPIRES_AT = _NOW + timedelta(minutes=15)
_REFRESH_EXPIRES_AT = _NOW + timedelta(days=7)
_USER_ID = UserId.from_public("user_00000000-0000-0000-0000-000000000001")


class _RecordingAdapter:
    def __init__(
        self,
        *,
        protocol_id: ProtocolId,
        correlation_method: CorrelationMethod,
        events: list[str],
        outcome: Authenticated | RestartAuthorization,
        extract: Callable[[CallbackContext], str],
        complete_error: Exception | None = None,
        begin_error: Exception | None = None,
    ) -> None:
        self.protocol_id = protocol_id
        self.correlation_method = correlation_method
        self.events = events
        self.outcome = outcome
        self.extract = extract
        self.complete_error = complete_error
        self.begin_error = begin_error
        self.extracted_contexts: list[CallbackContext] = []
        self.completed: list[tuple[ActiveProvider, LoginAttempt, CallbackContext]] = []
        self.begun: list[tuple[ActiveProvider, LoginAttempt, RequestContext]] = []
        self.replacement_cookie = CorrelationCookie(
            name="joysafeter_federation_attempt",
            value="signed-replacement",
            max_age_seconds=600,
        )

    def extract_attempt_id(self, context: CallbackContext) -> str:
        self.events.append("extract")
        self.extracted_contexts.append(context)
        return self.extract(context)

    async def begin_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: RequestContext,
    ) -> AuthorizationAction:
        self.events.append("begin")
        self.begun.append((provider, attempt, context))
        if self.begin_error is not None:
            raise self.begin_error
        return AuthorizationAction(
            authorization_url=f"https://provider.example/authorize?attempt={attempt.id}",
            correlation_cookie=self.replacement_cookie,
        )

    async def complete_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: CallbackContext,
    ) -> Authenticated | RestartAuthorization:
        self.events.append("complete")
        self.completed.append((provider, attempt, context))
        if self.complete_error is not None:
            raise self.complete_error
        return self.outcome


class _RecordingAdapterResolver:
    def __init__(self, adapters: dict[ProtocolId, _RecordingAdapter]) -> None:
        self.adapters = adapters
        self.required: list[ProtocolId] = []

    def require(self, protocol_id: ProtocolId) -> _RecordingAdapter:
        self.required.append(protocol_id)
        return self.adapters[protocol_id]


class _RecordingAttemptStore:
    def __init__(
        self,
        *,
        existing: LoginAttempt | None,
        events: list[str],
        consume_error: Exception | None = None,
        replace_error: Exception | None = None,
    ) -> None:
        self.existing = existing
        self.events = events
        self.consume_error = consume_error
        self.replace_error = replace_error
        self.created: list[LoginAttempt] = []
        self.consumed: list[str] = []
        self.replacements: list[tuple[LoginAttempt, LoginAttempt]] = []

    async def create(self, attempt: LoginAttempt) -> None:
        self.created.append(attempt)

    async def consume(self, attempt_id: str) -> LoginAttempt | None:
        self.events.append("consume")
        self.consumed.append(attempt_id)
        if self.consume_error is not None:
            raise self.consume_error
        return self.existing

    async def replace_for_retry(self, consumed: LoginAttempt, replacement: LoginAttempt) -> None:
        self.events.append("replace")
        self.replacements.append((consumed, replacement))
        if self.replace_error is not None:
            raise self.replace_error


class _RecordingAccountGateway:
    def __init__(
        self,
        *,
        events: list[str],
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.calls: list[tuple[FederatedPrincipal, AccountLinkPolicy]] = []

    async def resolve_or_create(
        self,
        principal: FederatedPrincipal,
        policy: AccountLinkPolicy,
    ) -> FederatedUser:
        self.events.append("account")
        self.calls.append((principal, policy))
        if self.error is not None:
            raise self.error
        return FederatedUser(user_id=_USER_ID, email=principal.email, is_new_user=False)

    async def list_accounts(self, user_id: UserId) -> tuple[object, ...]:
        raise AssertionError(f"unexpected account listing: {user_id}")

    async def unlink(self, user_id: UserId, provider_id: ProviderId) -> bool:
        raise AssertionError(f"unexpected account unlink: {user_id}, {provider_id}")


class _RecordingSessionGateway:
    def __init__(
        self,
        *,
        events: list[str],
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.calls: list[tuple[UserId, str]] = []

    async def issue(self, user_id: UserId, ip_address: str) -> IssuedAuthSession:
        self.events.append("session")
        self.calls.append((user_id, ip_address))
        if self.error is not None:
            raise self.error
        return IssuedAuthSession(
            access_token="access-token",
            refresh_token="refresh-token",
            csrf_token="csrf-token",
            access_expires_at=_ACCESS_EXPIRES_AT,
            refresh_expires_at=_REFRESH_EXPIRES_AT,
        )


def _oauth_provider() -> ActiveProvider:
    return ActiveProvider(
        id=ProviderId("github"),
        display_name="GitHub",
        icon="github",
        protocol=ProtocolId.OAUTH2,
        settings=OAuth2ProviderSettings(
            client_id="github-client",
            client_secret="github-secret",
            authorize_url="https://github.example/authorize",
            token_url="https://github.example/token",
            userinfo_url="https://github.example/user",
            issuer=None,
            scope="read:user user:email",
            user_mapping={"id": "id"},
        ),
    )


def _jd_provider() -> ActiveProvider:
    return ActiveProvider(
        id=ProviderId("jd"),
        display_name="JD SSO",
        icon="building",
        protocol=ProtocolId.JD_SSO,
        settings=JDSSOProviderSettings(
            client_id="jd-client",
            client_secret="jd-secret",
            authorize_url="https://sso.jd.example/login",
            userinfo_url="https://sso.jd.example/verifyTicket",
            scope="openid",
            user_mapping={"id": "userId"},
        ),
    )


def _registry() -> ProviderRegistry:
    return ProviderRegistry(
        [_oauth_provider(), _jd_provider()],
        FederationSettings(
            login_mode=LoginMode.CHOOSER,
            default_redirect_url="/managed/quickstart",
            allow_registration=True,
            auto_link_by_email=True,
        ),
    )


def _principal(provider_id: str = "github") -> FederatedPrincipal:
    return FederatedPrincipal(
        provider_id=ProviderId(provider_id),
        subject="subject-1",
        email="User@Example.com",
        email_verified=True,
        display_name="Example User",
        avatar_url="https://images.example/avatar.png",
        claims={"sub": "subject-1"},
    )


def _attempt(
    attempt_id: str,
    *,
    provider: str = "github",
    retry_count: int = 0,
    expires_at: datetime | None = None,
    redirect_uri: str | None = None,
    correlation_method: CorrelationMethod | None = None,
) -> LoginAttempt:
    return LoginAttempt(
        id=attempt_id,
        provider_id=ProviderId(provider),
        callback_url="/managed/dashboard",
        redirect_uri=redirect_uri or f"https://api.example.com/api/v1/auth/oauth/{provider}/callback",
        correlation_method=correlation_method
        or (CorrelationMethod.SIGNED_COOKIE if provider == "jd" else CorrelationMethod.OAUTH_STATE),
        retry_count=retry_count,
        created_at=_NOW - timedelta(minutes=1),
        expires_at=expires_at or (_NOW + timedelta(minutes=9)),
    )


def _callback_context(
    *,
    provider: str = "github",
    query: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> CallbackContext:
    return CallbackContext(
        base_url="https://api.example.com",
        request_url=f"https://api.example.com/api/v1/auth/oauth/{provider}/callback",
        client_ip="203.0.113.10",
        headers={"host": "api.example.com"},
        cookies=cookies or {},
        query=query or {},
    )


def _oauth_extract(context: CallbackContext) -> str:
    return context.query["state"]


def _jd_extract(context: CallbackContext) -> str:
    return context.cookies["joysafeter_federation_attempt"]


def _coordinator(
    *,
    stored_attempt: LoginAttempt | None = None,
    outcome: Authenticated | RestartAuthorization | None = None,
    provider: str = "github",
    complete_error: Exception | None = None,
    begin_error: Exception | None = None,
    account_error: Exception | None = None,
    session_error: Exception | None = None,
    replace_error: Exception | None = None,
    attempt_ids: Iterator[str] | None = None,
    account_gateway_configured: bool = True,
    session_gateway_configured: bool = True,
) -> tuple[
    FederatedLoginCoordinator,
    _RecordingAttemptStore,
    _RecordingAdapter,
    _RecordingAccountGateway,
    _RecordingSessionGateway,
    list[str],
]:
    events: list[str] = []
    resolved_outcome = outcome or Authenticated(_principal(provider))
    protocol_id = ProtocolId.JD_SSO if provider == "jd" else ProtocolId.OAUTH2
    correlation_method = CorrelationMethod.SIGNED_COOKIE if provider == "jd" else CorrelationMethod.OAUTH_STATE
    adapter = _RecordingAdapter(
        protocol_id=protocol_id,
        correlation_method=correlation_method,
        events=events,
        outcome=resolved_outcome,
        extract=_jd_extract if provider == "jd" else _oauth_extract,
        complete_error=complete_error,
        begin_error=begin_error,
    )
    resolver = _RecordingAdapterResolver({protocol_id: adapter})
    store = _RecordingAttemptStore(
        existing=stored_attempt,
        events=events,
        replace_error=replace_error,
    )
    account_gateway = _RecordingAccountGateway(events=events, error=account_error)
    session_gateway = _RecordingSessionGateway(events=events, error=session_error)
    coordinator = FederatedLoginCoordinator(
        registry=_registry(),
        adapters=resolver,
        attempt_store=store,
        account_gateway=account_gateway if account_gateway_configured else None,
        session_gateway=session_gateway if session_gateway_configured else None,
        attempt_id_factory=(lambda: next(attempt_ids)) if attempt_ids is not None else None,
        clock=lambda: _NOW,
    )
    return coordinator, store, adapter, account_gateway, session_gateway, events


@pytest.mark.parametrize(
    "malicious_callback_url",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "managed/dashboard",
        "/managed\\evil",
        "/%2f%2fevil.example/path",
        "/%5cevil.example/path",
        "/%25evil.example/path",
        "/../admin",
        "/%2e%2e/admin",
        "/managed\nnext",
        "/managed path",
        "/%GG",
        123,
    ],
)
def test_login_succeeded_redirect_path_revalidates_after_mutation(malicious_callback_url: object) -> None:
    result = LoginSucceeded(
        callback_url="/managed/dashboard",
        access_token="access-token",
        refresh_token="refresh-token",
        csrf_token="csrf-token",
        access_expires_at=_ACCESS_EXPIRES_AT,
        refresh_expires_at=_REFRESH_EXPIRES_AT,
    )

    assert result.redirect_path == "/managed/dashboard"

    object.__setattr__(result, "callback_url", malicious_callback_url)

    with pytest.raises(FederationError) as exc_info:
        _ = result.redirect_path

    assert exc_info.value.code == "FEDERATION_CALLBACK_FAILED"


@pytest.mark.asyncio
async def test_complete_login_consumes_attempt_before_adapter_account_and_session_work() -> None:
    attempt = _attempt("attempt-1")
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(stored_attempt=attempt)
    context = _callback_context(query={"state": "attempt-1", "code": "code-1"})

    result = await coordinator.complete_login(CompleteLoginCommand(provider_id="github"), context)

    assert events == ["extract", "consume", "complete", "account", "session"]
    assert store.consumed == ["attempt-1"]
    assert adapter.completed == [(_oauth_provider(), attempt, context)]
    assert account_gateway.calls == [
        (
            _principal(),
            AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
        )
    ]
    assert session_gateway.calls == [(_USER_ID, "203.0.113.10")]
    assert result == LoginSucceeded(
        callback_url="/managed/dashboard",
        access_token="access-token",
        refresh_token="refresh-token",
        csrf_token="csrf-token",
        access_expires_at=_ACCESS_EXPIRES_AT,
        refresh_expires_at=_REFRESH_EXPIRES_AT,
    )


@pytest.mark.parametrize(
    ("stored_attempt", "expected_code"),
    [
        (None, "FEDERATION_ATTEMPT_INVALID"),
        (_attempt("attempt-1", provider="jd"), "FEDERATION_ATTEMPT_MISMATCH"),
        (
            _attempt(
                "attempt-1",
                redirect_uri="https://api.example.com/api/v1/auth/oauth/google/callback",
            ),
            "FEDERATION_ATTEMPT_MISMATCH",
        ),
        (
            _attempt("attempt-1", correlation_method=CorrelationMethod.SIGNED_COOKIE),
            "FEDERATION_ATTEMPT_MISMATCH",
        ),
        (
            _attempt(
                "attempt-1",
                expires_at=_NOW,
                redirect_uri="https://api.example.com/api/v1/auth/oauth/google/callback",
            ),
            "FEDERATION_ATTEMPT_MISMATCH",
        ),
        (
            _attempt("attempt-1", expires_at=_NOW),
            "FEDERATION_ATTEMPT_EXPIRED",
        ),
    ],
    ids=[
        "missing",
        "provider-mismatch",
        "redirect-mismatch",
        "correlation-mismatch",
        "mismatch-before-expiry",
        "expired",
    ],
)
@pytest.mark.asyncio
async def test_complete_login_rejects_consumed_attempt_before_adapter_completion(
    stored_attempt: LoginAttempt | None,
    expected_code: str,
) -> None:
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(stored_attempt=stored_attempt)

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="github"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == expected_code
    assert store.consumed == ["attempt-1"]
    assert adapter.completed == []
    assert account_gateway.calls == []
    assert session_gateway.calls == []
    assert events == ["extract", "consume"]


@pytest.mark.asyncio
async def test_complete_login_requires_active_provider_before_correlation_extraction() -> None:
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(
        stored_attempt=_attempt("attempt-1")
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="missing"),
            _callback_context(query={"state": "attempt-1"}),
        )

    assert exc_info.value.code == "FEDERATION_PROVIDER_NOT_ACTIVE"
    assert store.consumed == []
    assert adapter.extracted_contexts == []
    assert account_gateway.calls == []
    assert session_gateway.calls == []
    assert events == []


@pytest.mark.parametrize(
    ("missing_gateway", "expected_message"),
    [
        ("account", "Federated account gateway is not configured"),
        ("session", "Auth session gateway is not configured"),
    ],
)
@pytest.mark.asyncio
async def test_complete_login_preflights_gateways_before_correlation_or_consumption(
    missing_gateway: str,
    expected_message: str,
) -> None:
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(
        stored_attempt=_attempt("attempt-1"),
        account_gateway_configured=missing_gateway != "account",
        session_gateway_configured=missing_gateway != "session",
    )

    with pytest.raises(RuntimeError, match=expected_message):
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="github"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert events == []
    assert adapter.extracted_contexts == []
    assert adapter.completed == []
    assert adapter.begun == []
    assert store.consumed == []
    assert store.replacements == []
    assert account_gateway.calls == []
    assert session_gateway.calls == []


@pytest.mark.asyncio
async def test_oauth_completion_uses_adapter_extracted_query_state() -> None:
    coordinator, store, adapter, _, _, _ = _coordinator(stored_attempt=_attempt("oauth-attempt"))
    context = _callback_context(
        query={"state": "oauth-attempt", "code": "code-1"},
        cookies={"joysafeter_federation_attempt": "wrong-cookie-attempt"},
    )

    await coordinator.complete_login(CompleteLoginCommand(provider_id="github"), context)

    assert adapter.extracted_contexts == [context]
    assert store.consumed == ["oauth-attempt"]


@pytest.mark.asyncio
async def test_jd_completion_uses_signed_cookie_without_query_state_fallback() -> None:
    coordinator, store, adapter, _, _, _ = _coordinator(
        stored_attempt=_attempt("jd-attempt", provider="jd"),
        provider="jd",
    )
    context = _callback_context(
        provider="jd",
        query={"state": "wrong-query-attempt"},
        cookies={"joysafeter_federation_attempt": "jd-attempt", "sso.jd.com": "ticket-1"},
    )

    await coordinator.complete_login(CompleteLoginCommand(provider_id="jd"), context)

    assert adapter.extracted_contexts == [context]
    assert store.consumed == ["jd-attempt"]


@pytest.mark.parametrize(
    ("boundary", "expected_events", "expected_account_calls", "expected_session_calls"),
    [
        ("adapter", ["extract", "consume", "complete"], 0, 0),
        ("account", ["extract", "consume", "complete", "account"], 1, 0),
        ("session", ["extract", "consume", "complete", "account", "session"], 1, 1),
    ],
)
@pytest.mark.asyncio
async def test_complete_login_propagates_boundary_failures_after_attempt_consumption(
    boundary: str,
    expected_events: list[str],
    expected_account_calls: int,
    expected_session_calls: int,
) -> None:
    error = FederationError(
        code=f"FEDERATION_{boundary.upper()}_FAILED",
        message=f"{boundary} failed",
    )
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(
        stored_attempt=_attempt("attempt-1"),
        complete_error=error if boundary == "adapter" else None,
        account_error=error if boundary == "account" else None,
        session_error=error if boundary == "session" else None,
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="github"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value is error
    assert store.consumed == ["attempt-1"]
    assert events == expected_events
    assert len(adapter.completed) == 1
    assert adapter.begun == []
    assert len(account_gateway.calls) == expected_account_calls
    assert len(session_gateway.calls) == expected_session_calls
    assert store.replacements == []


@pytest.mark.asyncio
async def test_jd_restart_is_allowed_once_and_atomically_replaces_attempt() -> None:
    consumed = _attempt("attempt-1", provider="jd", retry_count=0)
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(
        stored_attempt=consumed,
        provider="jd",
        outcome=RestartAuthorization(reason="jd_session_missing"),
        attempt_ids=iter(("attempt-2",)),
    )
    context = _callback_context(
        provider="jd",
        query={"state": "ignored-query-state"},
        cookies={"joysafeter_federation_attempt": "attempt-1"},
    )

    result = await coordinator.complete_login(CompleteLoginCommand(provider_id="jd"), context)

    assert events == ["extract", "consume", "complete", "begin", "replace"]
    assert len(store.replacements) == 1
    replaced, replacement = store.replacements[0]
    assert replaced is consumed
    assert replacement == LoginAttempt(
        id="attempt-2",
        provider_id=ProviderId("jd"),
        callback_url=consumed.callback_url,
        redirect_uri=consumed.redirect_uri,
        correlation_method=CorrelationMethod.SIGNED_COOKIE,
        retry_count=1,
        created_at=_NOW,
        expires_at=_NOW + timedelta(minutes=10),
    )
    assert adapter.begun == [(_jd_provider(), replacement, context)]
    assert account_gateway.calls == []
    assert session_gateway.calls == []
    assert result == LoginRestarted(
        authorization_action=AuthorizationAction(
            authorization_url="https://provider.example/authorize?attempt=attempt-2",
            correlation_cookie=adapter.replacement_cookie,
        ),
        clear_correlation_cookie=True,
    )


@pytest.mark.asyncio
async def test_second_jd_restart_is_rejected_after_consumption() -> None:
    coordinator, store, adapter, account_gateway, session_gateway, events = _coordinator(
        stored_attempt=_attempt("attempt-2", provider="jd", retry_count=1),
        provider="jd",
        outcome=RestartAuthorization(reason="jd_session_missing"),
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="jd"),
            _callback_context(
                provider="jd",
                cookies={"joysafeter_federation_attempt": "attempt-2"},
            ),
        )

    assert exc_info.value.code == "FEDERATION_RETRY_EXHAUSTED"
    assert store.consumed == ["attempt-2"]
    assert store.replacements == []
    assert adapter.begun == []
    assert account_gateway.calls == []
    assert session_gateway.calls == []
    assert events == ["extract", "consume", "complete"]


@pytest.mark.asyncio
async def test_restart_adapter_begin_failure_does_not_replace_attempt() -> None:
    error = FederationError(
        code="FEDERATION_UPSTREAM_UNAVAILABLE",
        message="Provider is unavailable",
        retryable=True,
    )
    coordinator, store, _, _, _, events = _coordinator(
        stored_attempt=_attempt("attempt-1", provider="jd"),
        provider="jd",
        outcome=RestartAuthorization(reason="jd_session_missing"),
        begin_error=error,
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="jd"),
            _callback_context(
                provider="jd",
                cookies={"joysafeter_federation_attempt": "attempt-1"},
            ),
        )

    assert exc_info.value is error
    assert store.replacements == []
    assert events == ["extract", "consume", "complete", "begin"]


@pytest.mark.asyncio
async def test_restart_replacement_failure_propagates_after_authorization_action() -> None:
    error = FederationError(
        code="FEDERATION_STATE_STORE_UNAVAILABLE",
        message="Federation login state is unavailable",
        retryable=True,
    )
    coordinator, store, adapter, _, _, events = _coordinator(
        stored_attempt=_attempt("attempt-1", provider="jd"),
        provider="jd",
        outcome=RestartAuthorization(reason="jd_session_missing"),
        replace_error=error,
        attempt_ids=iter(("attempt-2",)),
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="jd"),
            _callback_context(
                provider="jd",
                cookies={"joysafeter_federation_attempt": "attempt-1"},
            ),
        )

    assert exc_info.value is error
    assert len(adapter.begun) == 1
    assert len(store.replacements) == 1
    assert events == ["extract", "consume", "complete", "begin", "replace"]

# Identity Federation Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed OAuth/JD implementation with a cohesive user identity-federation domain whose configuration, protocol behavior, login attempts, account linking, API boundary, frontend behavior, and deployment activation are explicit and fail closed.

**Architecture:** Add one vertical bounded context at `app/joysafeter_identity_federation` with pure domain types and ports, application coordinators, infrastructure adapters, and a single bootstrap composition root. Provider definitions are compiled at startup into an immutable registry; deployment activation comes only from `IDENTITY_FEDERATION_PROVIDERS`; API routes contain no protocol, Redis, or account-provisioning logic.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, redis-py asyncio, httpx, PyYAML, pytest/pytest-asyncio, React/Next.js, TypeScript, Vitest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-15-identity-federation-domain-design.md`

## Global Constraints

- Keep the public HTTP paths `/api/v1/auth/oauth/providers`, `/api/v1/auth/oauth/{provider}`, `/api/v1/auth/oauth/{provider}/callback`, `/api/v1/auth/oauth/accounts/me`, and `/api/v1/auth/oauth/accounts/{provider}`.
- Do not add `enabled: auto`, environment-secret inference, protocol fallback, old/new config dual reads, or aliases for `OAUTH_CONFIG_PATH` and `SSO_DEFAULT_PROVIDER`.
- `IDENTITY_FEDERATION_PROVIDERS` is the only Provider activation source; missing or empty means no active external login Provider.
- `IDENTITY_FEDERATION_LOGIN_MODE` accepts only `chooser` and `redirect`; `redirect` requires at least one active Provider and targets the first configured Provider.
- Domain code must not import FastAPI, SQLAlchemy, Redis, httpx, yaml, global settings, AuthService, JWT helpers, or API DTOs.
- API code must not import Redis, YAML/config compiler internals, concrete protocol adapters, or compare protocol IDs.
- Protocol adapters must not import SQLAlchemy models, repositories, AuthService, organization/project services, or JWT helpers.
- Login attempts expire after 600 seconds and are consumed atomically at most once.
- Unknown protocols, unresolved active-provider environment variables, invalid URLs, malformed YAML, and invalid activation lists must block API startup.
- Loopback/private/link-local Provider endpoints are rejected except for Provider `local` when `ENVIRONMENT=development`; staging and production never receive this exception.
- Auto-link by email requires `principal.email_verified is True`, an active existing user, and an exact normalized email match.
- JD-derived `username@jd.com` email is unverified and cannot auto-link an existing user.
- Keep `deploy/docker/orchestrator-rs-jd.Dockerfile`; it is active for internal deployment.
- Preserve the existing OAuth account table and `(provider, provider_account_id)` unique index; no database migration is expected unless a test proves the current schema cannot represent the new model.
- Each task ends with focused tests and one reviewable commit. Do not mix Batch 0 Docker cleanup with federation-domain commits.

---

## Batch 0 — Close Existing Deployment Work

### Task 1: Preserve Source-Dockerfile Build Contracts

**Files:**
- Modify: `backend/tests/test_rebin_dockerfiles.py:1`
- Modify: `backend/env.example:228`
- Modify: `deploy/docker/orchestrator-rs.Dockerfile:35`
- Modify: `deploy/docker/orchestrator-rs-jd.Dockerfile:25`
- Modify: `deploy/docker/orchestrator-rs-binary.Dockerfile:10`

**Interfaces:**
- Consumes: Rust `include_str!("../../../../config/llm_catalog.yaml")` build-time path contract.
- Produces: Tracked regression tests proving both source Dockerfiles copy `backend/config` before Cargo builds and no Dockerfile exports dead `JOYSAFETER_ENABLED`.

- [ ] **Step 1: Add the failing tracked Dockerfile contract tests**

Append to `backend/tests/test_rebin_dockerfiles.py`:

```python
SOURCE_ORCHESTRATOR_DOCKERFILES = (
    "orchestrator-rs.Dockerfile",
    "orchestrator-rs-jd.Dockerfile",
)


@pytest.mark.parametrize("filename", SOURCE_ORCHESTRATOR_DOCKERFILES)
def test_orchestrator_source_dockerfile_copies_compile_time_inputs(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "COPY proto ./proto" in source
    assert "COPY backend/app/joysafeter_orchestrator_rs ./backend/app/joysafeter_orchestrator_rs" in source
    assert "COPY backend/config ./backend/config" in source
    assert source.index("COPY backend/config ./backend/config") < source.index("RUN cargo build")


@pytest.mark.parametrize(
    "filename",
    (*SOURCE_ORCHESTRATOR_DOCKERFILES, "orchestrator-rs-binary.Dockerfile"),
)
def test_orchestrator_dockerfiles_do_not_export_dead_global_enable_switch(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "JOYSAFETER_ENABLED" not in source
```

- [ ] **Step 2: Run the test against the pre-fix contract if reconstructing from a clean branch**

Run: `cd backend && uv run pytest tests/test_rebin_dockerfiles.py -q`

Expected before the JD Dockerfile fix: FAIL because `orchestrator-rs-jd.Dockerfile` lacks `COPY backend/config ./backend/config`.

- [ ] **Step 3: Keep the focused Dockerfile corrections**

The JD source Dockerfile must contain:

```dockerfile
COPY proto ./proto
COPY backend/app/joysafeter_orchestrator_rs ./backend/app/joysafeter_orchestrator_rs
COPY backend/config ./backend/config

WORKDIR /src/backend/app/joysafeter_orchestrator_rs
RUN cargo build --release --target ${TARGET}
```

Remove `ENV JOYSAFETER_ENABLED=true` from all three orchestrator Dockerfiles and remove `JOYSAFETER_ENABLED` from `backend/env.example`.

- [ ] **Step 4: Verify Docker contracts and syntax**

Run:

```bash
cd backend && uv run pytest tests/test_rebin_dockerfiles.py -q
cd .. && docker build --check -f deploy/docker/orchestrator-rs.Dockerfile .
docker build --check -f deploy/docker/orchestrator-rs-jd.Dockerfile .
git diff --check
```

Expected: pytest passes; both BuildKit checks report no errors; `git diff --check` is silent.

- [ ] **Step 5: Commit Batch 0 independently**

```bash
git add backend/env.example backend/tests/test_rebin_dockerfiles.py deploy/docker/orchestrator-rs.Dockerfile deploy/docker/orchestrator-rs-jd.Dockerfile deploy/docker/orchestrator-rs-binary.Dockerfile
git commit -m "fix(deploy): make orchestrator source builds self-contained"
```

---

## Batch 1 — Domain and Startup Configuration

### Task 2: Add Pure Federation Domain Types and Errors

**Files:**
- Create: `backend/app/joysafeter_identity_federation/__init__.py`
- Create: `backend/app/joysafeter_identity_federation/domain/__init__.py`
- Create: `backend/app/joysafeter_identity_federation/domain/models.py`
- Create: `backend/app/joysafeter_identity_federation/domain/errors.py`
- Test: `backend/tests/test_identity_federation_domain.py`

**Interfaces:**
- Consumes: None; this is the dependency root.
- Produces: `ProviderId`, `ProtocolId`, `LoginMode`, `CorrelationMethod`, `ProviderDescriptor`, `OAuth2ProviderSettings`, `JDSSOProviderSettings`, `ActiveProvider`, `FederationSettings`, `LoginAttempt`, `FederatedPrincipal`, `FederatedUser`, `IssuedAuthSession`, `ConfigurationIssue`, `FederationConfigurationError`, and `FederationError`.

- [ ] **Step 1: Write failing value-object and error tests**

Create `backend/tests/test_identity_federation_domain.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_identity_federation.domain.errors import (
    ConfigurationIssue,
    FederationConfigurationError,
)
from app.joysafeter_identity_federation.domain.models import (
    FederatedPrincipal,
    LoginAttempt,
    LoginMode,
    ProtocolId,
    ProviderId,
)

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("raw", ["", "JD", "jd sso", "jd/sso", "-jd"])
def test_provider_id_rejects_non_canonical_values(raw: str) -> None:
    with pytest.raises(ValueError):
        ProviderId(raw)


def test_login_attempt_is_expired_at_boundary() -> None:
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    attempt = LoginAttempt(
        id="attempt-1",
        provider_id=ProviderId("jd"),
        callback_url="/managed/quickstart",
        redirect_uri="https://api.example.com/api/v1/auth/oauth/jd/callback",
        correlation_method=CorrelationMethod.SIGNED_COOKIE,
        retry_count=0,
        created_at=now - timedelta(seconds=600),
        expires_at=now,
    )

    assert attempt.is_expired(now) is True


def test_federated_principal_requires_stable_subject() -> None:
    with pytest.raises(ValueError):
        FederatedPrincipal(
            provider_id=ProviderId("github"),
            subject="",
            email="user@example.com",
            email_verified=True,
            display_name="User",
            avatar_url=None,
            claims={},
        )


def test_configuration_error_renders_all_issues_in_order() -> None:
    error = FederationConfigurationError(
        [
            ConfigurationIssue("jd", "client_id", "FEDERATION_ENV_UNRESOLVED", "JD_CLIENT_ID is unset"),
            ConfigurationIssue("jd", "userinfo_url", "FEDERATION_PROVIDER_CONFIG_INVALID", "URL is invalid"),
        ]
    )

    assert [issue.field for issue in error.issues] == ["client_id", "userinfo_url"]
    assert "FEDERATION_ENV_UNRESOLVED" in str(error)
```

- [ ] **Step 2: Run the new tests to verify import failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_domain.py -q`

Expected: FAIL with `ModuleNotFoundError: app.joysafeter_identity_federation`.

- [ ] **Step 3: Implement immutable domain models**

Implement the public shape in `domain/models.py`:

```python
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeAlias


class ProtocolId(StrEnum):
    OAUTH2 = "oauth2"
    JD_SSO = "jd_sso"


class LoginMode(StrEnum):
    CHOOSER = "chooser"
    REDIRECT = "redirect"


class CorrelationMethod(StrEnum):
    OAUTH_STATE = "oauth_state"
    SIGNED_COOKIE = "signed_cookie"


@dataclass(frozen=True, slots=True)
class ProviderId:
    value: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.value) is None:
            raise ValueError("ProviderId must be lowercase alphanumeric with optional '-' or '_'")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    id: ProviderId
    display_name: str
    icon: str


@dataclass(frozen=True, slots=True)
class OAuth2ProviderSettings:
    client_id: str
    client_secret: str
    authorize_url: str | None
    token_url: str | None
    userinfo_url: str | None
    issuer: str | None
    scope: str
    user_mapping: Mapping[str, str]
    token_endpoint_auth_method: str = "client_secret_basic"
    userinfo_headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class JDSSOProviderSettings:
    client_id: str
    client_secret: str
    authorize_url: str
    userinfo_url: str
    scope: str
    user_mapping: Mapping[str, str]


ProviderProtocolSettings: TypeAlias = OAuth2ProviderSettings | JDSSOProviderSettings


@dataclass(frozen=True, slots=True)
class ActiveProvider:
    id: ProviderId
    display_name: str
    icon: str
    protocol: ProtocolId
    settings: ProviderProtocolSettings


@dataclass(frozen=True, slots=True)
class FederationSettings:
    login_mode: LoginMode
    default_redirect_url: str
    allow_registration: bool
    auto_link_by_email: bool


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    id: str
    provider_id: ProviderId
    callback_url: str
    redirect_uri: str
    correlation_method: CorrelationMethod
    retry_count: int
    created_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at
```

Add `FederatedPrincipal`, `FederatedUser`, `FederatedAccountView`, and `IssuedAuthSession` as frozen slot dataclasses. `FederatedUser` contains `user_id`, `email`, and `is_new_user`. `FederatedAccountView` contains `id`, `provider_id`, `subject`, `email`, and `created_at`. `IssuedAuthSession` contains `access_token`, `refresh_token`, `csrf_token`, `access_expires_at`, and `refresh_expires_at`. Normalize `email` to lowercase/trimmed when present; preserve `claims` as an immutable mapping; reject an empty `subject`.

Implement `domain/errors.py` with a frozen `ConfigurationIssue`, aggregate `FederationConfigurationError(RuntimeError)`, and `FederationError(Exception)` carrying `code`, `message`, `retryable`, `user_action`, and non-sensitive `data`.

- [ ] **Step 4: Run domain tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_domain.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain root**

```bash
git add backend/app/joysafeter_identity_federation backend/tests/test_identity_federation_domain.py
git commit -m "feat(identity): define federation domain model"
```

### Task 3: Define Ports, Correlation Contexts, and Account-Link Policy

**Files:**
- Create: `backend/app/joysafeter_identity_federation/domain/ports.py`
- Create: `backend/app/joysafeter_identity_federation/domain/policies.py`
- Modify: `backend/app/joysafeter_identity_federation/domain/models.py`
- Modify: `backend/tests/test_identity_federation_domain.py`
- Create: `backend/tests/test_identity_federation_architecture.py`

**Interfaces:**
- Consumes: Task 2 domain models and errors.
- Produces: `ProviderRegistryPort`, `ProtocolAdapter`, `ProtocolAdapterResolver`, `LoginAttemptStore`, `FederatedAccountGateway`, `AuthSessionGateway`, `RequestContext`, `CallbackContext`, `AuthorizationAction`, `Authenticated`, `RestartAuthorization`, and `AccountLinkPolicy`.

- [ ] **Step 1: Add failing policy and import-boundary tests**

Add to `test_identity_federation_domain.py`:

```python
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.policies import AccountLinkPolicy


def test_auto_link_rejects_unverified_external_email() -> None:
    policy = AccountLinkPolicy(allow_registration=True, auto_link_by_email=True)

    with pytest.raises(FederationError) as exc_info:
        policy.require_auto_link_allowed(
            principal_email="user@example.com",
            principal_email_verified=False,
            existing_user_email="user@example.com",
            existing_user_active=True,
        )

    assert exc_info.value.code == "FEDERATION_ACCOUNT_LINK_REQUIRED"


def test_auto_link_accepts_verified_exact_normalized_email() -> None:
    policy = AccountLinkPolicy(allow_registration=True, auto_link_by_email=True)

    policy.require_auto_link_allowed(
        principal_email=" User@Example.com ",
        principal_email_verified=True,
        existing_user_email="user@example.com",
        existing_user_active=True,
    )
```

Create `test_identity_federation_architecture.py` using `ast` and assert forbidden import roots are absent from `joysafeter_identity_federation/domain`:

```python
FORBIDDEN_DOMAIN_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "redis",
    "httpx",
    "yaml",
    "app.joysafeter_shared.config.settings",
    "app.joysafeter_domain.services.joysafeter_auth_service",
}
```

- [ ] **Step 2: Run the tests to verify missing ports/policy**

Run: `cd backend && uv run pytest tests/test_identity_federation_domain.py tests/test_identity_federation_architecture.py -q`

Expected: FAIL because `domain.policies` and `domain.ports` do not exist.

- [ ] **Step 3: Implement framework-free ports and policy**

Add transport-neutral contexts to `domain/models.py`:

```python
@dataclass(frozen=True, slots=True)
class RequestContext:
    base_url: str
    request_url: str
    client_ip: str
    headers: Mapping[str, str]
    cookies: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CallbackContext(RequestContext):
    query: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CorrelationCookie:
    name: str
    value: str
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class AuthorizationAction:
    authorization_url: str
    correlation_cookie: CorrelationCookie | None = None


@dataclass(frozen=True, slots=True)
class Authenticated:
    principal: FederatedPrincipal


@dataclass(frozen=True, slots=True)
class RestartAuthorization:
    reason: str
```

Define `Protocol` interfaces in `domain/ports.py` with these exact methods:

```python
class ProviderRegistryPort(Protocol):
    settings: FederationSettings
    def require(self, provider_id: ProviderId) -> ActiveProvider: ...
    def list_public(self) -> tuple[ProviderDescriptor, ...]: ...


class ProtocolAdapter(Protocol):
    protocol_id: ProtocolId
    correlation_method: CorrelationMethod
    def extract_attempt_id(self, context: CallbackContext) -> str: ...
    async def begin_login(self, provider: ActiveProvider, attempt: LoginAttempt, context: RequestContext) -> AuthorizationAction: ...
    async def complete_login(self, provider: ActiveProvider, attempt: LoginAttempt, context: CallbackContext) -> Authenticated | RestartAuthorization: ...


class ProtocolAdapterResolver(Protocol):
    def require(self, protocol_id: ProtocolId) -> ProtocolAdapter: ...


class LoginAttemptStore(Protocol):
    async def create(self, attempt: LoginAttempt) -> None: ...
    async def consume(self, attempt_id: str) -> LoginAttempt | None: ...
    async def replace_for_retry(self, consumed: LoginAttempt, replacement: LoginAttempt) -> None: ...


class FederatedAccountGateway(Protocol):
    async def resolve_or_create(self, principal: FederatedPrincipal, policy: AccountLinkPolicy) -> FederatedUser: ...
    async def list_accounts(self, user_id: str) -> tuple[FederatedAccountView, ...]: ...
    async def unlink(self, user_id: str, provider_id: ProviderId) -> bool: ...


class AuthSessionGateway(Protocol):
    async def issue(self, user_id: str, ip_address: str) -> IssuedAuthSession: ...
```

The types crossing these ports must be domain dataclasses, never SQLAlchemy models.

Implement `AccountLinkPolicy.require_auto_link_allowed()` with exact normalized-email, verified-email, and active-user rules.

- [ ] **Step 4: Run policy and architecture tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_domain.py tests/test_identity_federation_architecture.py -q`

Expected: PASS.

- [ ] **Step 5: Commit ports and policy**

```bash
git add backend/app/joysafeter_identity_federation/domain backend/tests/test_identity_federation_domain.py backend/tests/test_identity_federation_architecture.py
git commit -m "feat(identity): define federation ports and policies"
```

### Task 4: Add Protocol Schema and Runtime Adapter Registries

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/__init__.py`
- Create: `backend/app/joysafeter_identity_federation/infrastructure/protocols/__init__.py`
- Create: `backend/app/joysafeter_identity_federation/infrastructure/protocols/base.py`
- Create: `backend/app/joysafeter_identity_federation/infrastructure/protocols/schemas.py`
- Test: `backend/tests/test_identity_federation_protocol_registry.py`

**Interfaces:**
- Consumes: `ProtocolId`, protocol settings dataclasses, and `ProtocolAdapter`.
- Produces: `ProtocolSchemaRegistry.register()/require()/validate_configuration()`, empty `ProtocolAdapterRegistry.register()/require()`, `OAuth2ConfigSchema`, and `JDSSOConfigSchema`.

- [ ] **Step 1: Write failing registry/schema tests**

Create `test_identity_federation_protocol_registry.py` with a fake adapter and these assertions:

```python
def test_unknown_protocol_never_falls_back() -> None:
    registry = ProtocolSchemaRegistry()

    with pytest.raises(FederationConfigurationError) as exc_info:
        registry.require("saml")

    assert exc_info.value.issues[0].code == "FEDERATION_PROTOCOL_UNKNOWN"


def test_duplicate_protocol_registration_fails() -> None:
    registry = ProtocolSchemaRegistry()
    registry.register(_FakeProtocolDefinition())

    with pytest.raises(RuntimeError, match="already registered"):
        registry.register(_FakeProtocolDefinition())


def test_jd_schema_does_not_require_token_url() -> None:
    parsed = JDSSOConfigSchema.model_validate(
        {
            "client_id": "jd-client",
            "client_secret": "jd-secret",
            "authorize_url": "https://sso.jd.com/login",
            "userinfo_url": "https://sso.jd.com/verifyTicket",
            "scope": "openid email",
            "user_mapping": {"id": "userId", "email": "email", "name": "username", "avatar": ""},
        }
    )

    assert parsed.client_id == "jd-client"
```

- [ ] **Step 2: Run the test to verify missing infrastructure**

Run: `cd backend && uv run pytest tests/test_identity_federation_protocol_registry.py -q`

Expected: FAIL with missing module imports.

- [ ] **Step 3: Implement strict schemas and registry**

Use Pydantic v2 models with `ConfigDict(extra="forbid")`. `OAuth2ConfigSchema` requires client credentials plus either `issuer` or explicit authorize/token URLs. `JDSSOConfigSchema` requires client credentials, authorize URL, and userinfo URL and contains no `token_url` field.

`ProtocolSchemaRegistry` stores `ProtocolDefinition(protocol_id, schema_type, to_domain_settings)` and can validate configuration before concrete runtime adapters exist. `ProtocolAdapterRegistry` stores concrete `ProtocolAdapter` instances and remains empty until Task 14 composes the runtime after Tasks 8 and 9. Both `require()` methods raise `FEDERATION_PROTOCOL_UNKNOWN`; neither may instantiate or return OAuth2 for an unknown key.

- [ ] **Step 4: Run registry tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_protocol_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit protocol contracts**

```bash
git add backend/app/joysafeter_identity_federation/infrastructure backend/tests/test_identity_federation_protocol_registry.py
git commit -m "feat(identity): add strict federation protocol registry"
```

### Task 5: Compile Deployment Configuration into an Immutable Registry

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/templates.py`
- Create: `backend/app/joysafeter_identity_federation/infrastructure/registry.py`
- Create: `backend/app/joysafeter_identity_federation/infrastructure/config.py`
- Create: `backend/config/identity_federation_providers.yaml`
- Modify: `backend/app/joysafeter_shared/config/settings.py:633`
- Test: `backend/tests/test_identity_federation_config.py`

**Interfaces:**
- Consumes: Task 4 protocol schema registry/config schemas and Task 2 domain models.
- Produces: `compile_federation_configuration(config_path, active_provider_names, login_mode, application_environment, schema_registry, environ) -> CompiledFederationConfiguration`, immutable `ProviderRegistry`, and new settings fields.

- [ ] **Step 1: Write failing configuration matrix tests**

Create `test_identity_federation_config.py` using `tmp_path` and a real `ProtocolSchemaRegistry` populated with OAuth2 and JD protocol definitions. Include this parametrized activation test:

```python
@pytest.mark.parametrize(
    ("providers", "login_mode", "expected_code"),
    [
        ("jd,jd", "chooser", "FEDERATION_PROVIDER_DUPLICATE"),
        ("unknown", "chooser", "FEDERATION_PROVIDER_UNKNOWN"),
        ("", "redirect", "FEDERATION_LOGIN_MODE_INVALID"),
        ("jd", "automatic", "FEDERATION_LOGIN_MODE_INVALID"),
    ],
)
def test_invalid_activation_contract_fails(providers: str, login_mode: str, expected_code: str, tmp_path: Path) -> None:
    path = _write_catalog(tmp_path)

    with pytest.raises(FederationConfigurationError) as exc_info:
        compile_federation_configuration(
            config_path=path,
            active_provider_names=providers,
            login_mode=login_mode,
            application_environment="development",
            schema_registry=_schema_registry(),
            environ=_complete_env(),
        )

    assert expected_code in {issue.code for issue in exc_info.value.issues}
```

Add these concrete tests:

```python
def test_empty_activation_builds_empty_registry(tmp_path: Path) -> None:
    compiled = _compile(tmp_path, providers="", login_mode="chooser", environ={})
    assert compiled.registry.list_public() == ()


def test_active_provider_reports_every_unresolved_environment_value(tmp_path: Path) -> None:
    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="redirect", environ={"JD_CLIENT_ID": "client"})

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("client_secret", "FEDERATION_ENV_UNRESOLVED"),
        ("authorize_url", "FEDERATION_ENV_UNRESOLVED"),
        ("userinfo_url", "FEDERATION_ENV_UNRESOLVED"),
    ]


def test_inactive_provider_does_not_require_deployment_secrets(tmp_path: Path) -> None:
    compiled = _compile(tmp_path, providers="github", login_mode="chooser", environ=_github_env())
    assert [item.id.value for item in compiled.registry.list_public()] == ["github"]


def test_provider_order_and_registry_immutability(tmp_path: Path) -> None:
    compiled = _compile(tmp_path, providers="jd,github", login_mode="chooser", environ=_complete_env())
    assert [item.id.value for item in compiled.registry.list_public()] == ["jd", "github"]
    with pytest.raises(TypeError):
        compiled.registry.providers[ProviderId("google")] = compiled.registry.require(ProviderId("github"))
```

The unknown-protocol case is already covered by the activation matrix and must be run for both active and inactive catalog entries.

- [ ] **Step 2: Run configuration tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_config.py -q`

Expected: FAIL because compiler and registry do not exist.

- [ ] **Step 3: Implement the compiler pipeline**

Implement these exact stages in `config.py`:

```python
def compile_federation_configuration(
    *,
    config_path: Path,
    active_provider_names: str,
    login_mode: str,
    application_environment: str,
    schema_registry: ProtocolSchemaRegistry,
    environ: Mapping[str, str],
) -> CompiledFederationConfiguration:
    raw = _load_yaml(config_path)
    document = CatalogDocument.model_validate(raw)
    requested = _parse_active_provider_names(active_provider_names)
    parsed_mode = _parse_login_mode(login_mode, requested)
    providers, issues = _compile_active_providers(
        document,
        requested,
        application_environment,
        schema_registry,
        environ,
    )
    if issues:
        raise FederationConfigurationError(issues)
    return CompiledFederationConfiguration(
        registry=ProviderRegistry(providers, _compile_settings(document.settings, parsed_mode)),
    )
```

The YAML loader may catch `yaml.YAMLError` only to convert it into `FEDERATION_CONFIG_YAML_INVALID`; it must not log-and-continue. Expand `${NAME}` only for active Providers and append one `FEDERATION_ENV_UNRESOLVED` issue per missing variable. Validate all Provider names and protocol IDs even when inactive.

Copy the existing GitHub/Google/Microsoft/GitLab template values into `templates.py`. Create `identity_federation_providers.yaml` without any `enabled` keys and without JD `token_url`.

Add settings fields:

```python
identity_federation_providers: str = Field(default="", validation_alias="IDENTITY_FEDERATION_PROVIDERS")
identity_federation_config_path: Optional[str] = Field(default=None, validation_alias="IDENTITY_FEDERATION_CONFIG_PATH")
identity_federation_login_mode: str = Field(default="chooser", validation_alias="IDENTITY_FEDERATION_LOGIN_MODE")
```

Keep old `oauth_config_path` until Task 16 removes the old runtime path; do not read it from the new compiler.

- [ ] **Step 4: Run compiler tests and Ruff**

Run:

```bash
cd backend
uv run pytest tests/test_identity_federation_config.py tests/test_identity_federation_protocol_registry.py -q
uv run ruff check app/joysafeter_identity_federation tests/test_identity_federation_config.py tests/test_identity_federation_protocol_registry.py
```

Expected: PASS.

- [ ] **Step 5: Commit strict configuration**

```bash
git add backend/app/joysafeter_identity_federation/infrastructure backend/app/joysafeter_shared/config/settings.py backend/config/identity_federation_providers.yaml backend/tests/test_identity_federation_config.py
git commit -m "feat(identity): compile federation providers at startup"
```

### Task 6: Add Configuration Bootstrap and Startup Failure Contract

**Files:**
- Create: `backend/app/joysafeter_identity_federation/bootstrap.py`
- Modify: `backend/app/joysafeter_api/startup.py:13`
- Test: `backend/tests/test_identity_federation_startup.py`

**Interfaces:**
- Consumes: Configuration compiler, protocol schema registry, global settings.
- Produces: `initialize_identity_federation_configuration() -> CompiledFederationConfiguration`, `get_identity_federation_configuration()`, and startup fail-fast integration. Runtime adapters are composed later in Task 14.

- [ ] **Step 1: Write failing startup tests**

Create `test_identity_federation_startup.py`:

```python
@pytest.mark.no_db
def test_initialize_caches_one_immutable_configuration(monkeypatch, tmp_path) -> None:
    _configure_empty_federation(monkeypatch, tmp_path)

    first = initialize_identity_federation_configuration(force=True)
    second = get_identity_federation_configuration()

    assert second is first
    assert first.registry.list_public() == ()


@pytest.mark.no_db
def test_initialize_propagates_configuration_error(monkeypatch, tmp_path) -> None:
    path = tmp_path / "providers.yaml"
    path.write_text("providers: {jd: {protocol: unknown}}")
    monkeypatch.setattr(settings, "identity_federation_config_path", str(path))
    monkeypatch.setattr(settings, "identity_federation_providers", "jd")

    with pytest.raises(FederationConfigurationError):
        initialize_identity_federation_configuration(force=True)
```

Add this async startup propagation test:

```python
@pytest.mark.asyncio
@pytest.mark.no_db
async def test_api_startup_does_not_swallow_federation_configuration_error(monkeypatch) -> None:
    error = FederationConfigurationError(
        [ConfigurationIssue("jd", "client_secret", "FEDERATION_ENV_UNRESOLVED", "JD_CLIENT_SECRET is unset")]
    )

    def _raise() -> None:
        raise error

    monkeypatch.setattr(startup_module, "initialize_identity_federation_configuration", _raise)

    with pytest.raises(FederationConfigurationError) as exc_info:
        await startup_module.run_api_startup()

    assert exc_info.value is error
```

- [ ] **Step 2: Run startup tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_startup.py -q`

Expected: FAIL because bootstrap is missing.

- [ ] **Step 3: Implement bootstrap and wire startup**

`initialize_identity_federation_configuration()` resolves the default config path under `backend/config`, registers the built-in protocol schemas, compiles configuration, caches the immutable result, and logs only active Provider IDs and login mode. It must not instantiate HTTP, Redis, correlation, or database adapters.

At the start of `run_api_startup()` call:

```python
from app.joysafeter_identity_federation.bootstrap import initialize_identity_federation_configuration

initialize_identity_federation_configuration()
```

Do not wrap this call in `try/except`. A configuration failure must abort startup.

- [ ] **Step 4: Run startup/config tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_startup.py tests/test_identity_federation_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit startup composition**

```bash
git add backend/app/joysafeter_identity_federation/bootstrap.py backend/app/joysafeter_api/startup.py backend/tests/test_identity_federation_startup.py
git commit -m "feat(identity): fail fast on federation configuration"
```

---

## Batch 2 — Login Attempt and Protocol Ownership

### Task 7: Implement Atomic Redis Login Attempts and Signed JD Correlation

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/state_store.py`
- Create: `backend/app/joysafeter_identity_federation/infrastructure/correlation.py`
- Test: `backend/tests/test_identity_federation_state_store.py`
- Test: `backend/tests/test_identity_federation_correlation.py`

**Interfaces:**
- Consumes: `LoginAttemptStore`, `LoginAttempt`, and an application security secret injected into the correlation codec constructor.
- Produces: `RedisLoginAttemptStore`, `SignedCorrelationCodec.sign()`, and `verify()`.

- [ ] **Step 1: Write failing atomic-consume and signature tests**

Use a fake async Redis client that implements `set` and `eval`. Assert:

```python
@pytest.mark.asyncio
async def test_consume_returns_attempt_once() -> None:
    redis = _FakeRedis()
    store = RedisLoginAttemptStore(lambda: redis)
    attempt = _attempt("attempt-1")
    await store.create(attempt)

    assert await store.consume("attempt-1") == attempt
    assert await store.consume("attempt-1") is None


@pytest.mark.asyncio
async def test_missing_redis_fails_closed() -> None:
    store = RedisLoginAttemptStore(lambda: None)

    with pytest.raises(FederationError) as exc_info:
        await store.create(_attempt("attempt-1"))

    assert exc_info.value.code == "FEDERATION_STATE_STORE_UNAVAILABLE"


def test_signed_correlation_rejects_tampering_and_expiry() -> None:
    codec = SignedCorrelationCodec(secret=b"application-secret", cookie_name="federation_attempt")
    value = codec.sign("attempt-1", expires_at=1_786_748_600)

    assert codec.verify(value, now_epoch=1_786_748_000) == "attempt-1"
    with pytest.raises(FederationError):
        codec.verify(value + "x", now_epoch=1_786_748_000)
    with pytest.raises(FederationError):
        codec.verify(value, now_epoch=1_786_748_601)
```

- [ ] **Step 2: Run tests to verify missing implementations**

Run: `cd backend && uv run pytest tests/test_identity_federation_state_store.py tests/test_identity_federation_correlation.py -q`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement fail-closed storage and HMAC codec**

Use Redis key `identity_federation:attempt:{attempt_id}`. Create with `SET key value NX EX 600`; treat `False` as an ID collision. Consume with one Lua script:

```lua
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
```

Serialize only LoginAttempt fields. Parse malformed stored JSON as `FEDERATION_ATTEMPT_INVALID` and do not return partial data.

`SignedCorrelationCodec` must derive `HMAC-SHA256(application_secret, "joysafeter:identity-federation:correlation:v1")`, encode `attempt_id.expiry.signature` with URL-safe base64, and compare signatures with `hmac.compare_digest`.

- [ ] **Step 4: Run state tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_state_store.py tests/test_identity_federation_correlation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit attempt infrastructure**

```bash
git add backend/app/joysafeter_identity_federation/infrastructure/state_store.py backend/app/joysafeter_identity_federation/infrastructure/correlation.py backend/tests/test_identity_federation_state_store.py backend/tests/test_identity_federation_correlation.py
git commit -m "feat(identity): add atomic federation login attempts"
```

### Task 8: Implement the Complete OAuth2/OIDC Adapter

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/protocols/oauth2.py`
- Test: `backend/tests/test_identity_federation_oauth2_adapter.py`

**Interfaces:**
- Consumes: `ProtocolAdapter`, OAuth2 settings, endpoint SSRF guard, and injected `httpx.AsyncClient` factory.
- Produces: `OAuth2Adapter.begin_login()`, `extract_attempt_id()`, and `complete_login()` returning a verified `FederatedPrincipal`.

- [ ] **Step 1: Write failing adapter contract tests**

Use `httpx.MockTransport` and assert:

```python
@pytest.mark.asyncio
async def test_begin_login_uses_attempt_id_as_state() -> None:
    adapter = OAuth2Adapter(client_factory=_unused_client_factory)
    action = await adapter.begin_login(_github_provider(), _attempt("attempt-1"), _request_context())

    parsed = parse_qs(urlparse(action.authorization_url).query)
    assert parsed["state"] == ["attempt-1"]
    assert parsed["redirect_uri"] == [_attempt("attempt-1").redirect_uri]


def test_extract_attempt_id_requires_state() -> None:
    adapter = OAuth2Adapter(client_factory=_unused_client_factory)

    with pytest.raises(FederationError) as exc_info:
        adapter.extract_attempt_id(_callback_context(query={}))

    assert exc_info.value.code == "FEDERATION_ATTEMPT_INVALID"


@pytest.mark.asyncio
async def test_oidc_email_verified_claim_controls_principal() -> None:
    adapter = OAuth2Adapter(client_factory=_mock_oidc_client)
    outcome = await adapter.complete_login(
        _oidc_provider(),
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.subject == "subject-1"
    assert outcome.principal.email_verified is True
```

Add these concrete cases to the same test file:

```python
@pytest.mark.parametrize(
    ("query", "expected_code"),
    [
        ({"state": "attempt-1", "error": "access_denied"}, "FEDERATION_UPSTREAM_DENIED"),
        ({"state": "attempt-1"}, "FEDERATION_CALLBACK_INVALID"),
    ],
)
@pytest.mark.asyncio
async def test_callback_query_failures_are_typed(query: dict[str, str], expected_code: str) -> None:
    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_unused_client_factory).complete_login(
            _github_provider(),
            _attempt("attempt-1"),
            _callback_context(query=query),
        )

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("responses", "expected_code"),
    [
        ({"token": (502, {})}, "FEDERATION_UPSTREAM_UNAVAILABLE"),
        ({"token": (200, {"access_token": "token"}), "userinfo": (503, {})}, "FEDERATION_UPSTREAM_UNAVAILABLE"),
    ],
)
@pytest.mark.asyncio
async def test_upstream_failures_do_not_leak_response_data(responses, expected_code: str) -> None:
    with pytest.raises(FederationError) as exc_info:
        await OAuth2Adapter(client_factory=_client_factory(responses)).complete_login(
            _github_provider(),
            _attempt("attempt-1"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == expected_code
    assert "access_token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_github_primary_verified_email_is_authoritative() -> None:
    outcome = await OAuth2Adapter(client_factory=_github_client_factory()).complete_login(
        _github_provider(),
        _attempt("attempt-1"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.email == "verified@example.com"
    assert outcome.principal.email_verified is True


@pytest.mark.asyncio
async def test_oidc_discovery_is_cached_by_issuer() -> None:
    transport, calls = _counting_discovery_transport()
    adapter = OAuth2Adapter(client_factory=lambda: httpx.AsyncClient(transport=transport))

    await adapter.begin_login(_oidc_provider(), _attempt("attempt-1"), _request_context())
    await adapter.begin_login(_oidc_provider(), _attempt("attempt-2"), _request_context())

    assert calls["discovery"] == 1
```

Add these compile-time URL policy tests to `test_identity_federation_config.py`:

```python
def test_local_loopback_provider_is_allowed_only_in_development(tmp_path: Path) -> None:
    compiled = _compile_local_provider(tmp_path, environment="development")
    assert [item.id.value for item in compiled.registry.list_public()] == ["local"]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_local_loopback_provider_is_rejected_outside_development(tmp_path: Path, environment: str) -> None:
    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile_local_provider(tmp_path, environment=environment)

    assert "FEDERATION_PROVIDER_CONFIG_INVALID" in {issue.code for issue in exc_info.value.issues}
```

- [ ] **Step 2: Run OAuth2 tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_oauth2_adapter.py -q`

Expected: FAIL because the adapter is missing.

- [ ] **Step 3: Move OAuth2 behavior behind the adapter**

Implement authorization URL generation, OIDC discovery, token exchange, userinfo fetch, GitHub email fetch, and mapping in this adapter. Validate every discovered or configured endpoint through `validate_url()` before sending a request.

Email verification rules:

```python
if provider.id.value == "github":
    email, email_verified = await self._fetch_verified_github_email(access_token)
else:
    email = mapped_email
    email_verified = raw_userinfo.get("email_verified") is True
```

Never return access/refresh tokens in `FederatedPrincipal.claims`; keep only mapped identity claims required for account metadata.

- [ ] **Step 4: Run adapter and SSRF tests**

Run:

```bash
cd backend
uv run pytest tests/test_identity_federation_oauth2_adapter.py tests/test_oauth_async_boundary_contract.py -q
uv run ruff check app/joysafeter_identity_federation/infrastructure/protocols/oauth2.py tests/test_identity_federation_oauth2_adapter.py
```

Expected: New adapter tests pass. The old boundary tests continue exercising the old path and remain green until Task 15 switches routes.

- [ ] **Step 5: Commit OAuth2 adapter**

```bash
git add backend/app/joysafeter_identity_federation/infrastructure/protocols/oauth2.py backend/tests/test_identity_federation_oauth2_adapter.py
git commit -m "feat(identity): encapsulate oauth2 federation protocol"
```

### Task 9: Implement the Complete JD SSO Adapter

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/protocols/jd_sso.py`
- Test: `backend/tests/test_identity_federation_jd_adapter.py`

**Interfaces:**
- Consumes: `SignedCorrelationCodec`, JD settings, `ProtocolAdapter`, and injected HTTP client factory.
- Produces: `JDSSOAdapter` owning authorize URL, correlation cookie, ticket signature, verifyTicket, identity mapping, and restart outcome.

- [ ] **Step 1: Write failing JD protocol tests**

Include deterministic time and this signature assertion:

```python
def test_jd_signature_matches_reference_vector() -> None:
    assert JDSSOAdapter.compute_signature(
        client_secret="secret",
        timestamp_ms=1_700_000_000_000,
        ticket="ticket",
    ) == hashlib.md5(b"secret1700000000000ticket").hexdigest()


@pytest.mark.asyncio
async def test_begin_login_sets_signed_correlation_cookie() -> None:
    adapter = _adapter()
    action = await adapter.begin_login(_jd_provider(), _attempt("attempt-1"), _request_context())

    assert action.authorization_url.startswith("https://sso.jd.com/")
    assert action.correlation_cookie is not None
    assert action.correlation_cookie.name == "joysafeter_federation_attempt"


@pytest.mark.asyncio
async def test_missing_jd_session_requests_one_bounded_restart() -> None:
    outcome = await _adapter().complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context(query={}, cookies={"joysafeter_federation_attempt": _signed("attempt-1")}),
    )

    assert outcome == RestartAuthorization(reason="jd_session_missing")


@pytest.mark.asyncio
async def test_derived_jd_email_is_unverified() -> None:
    outcome = await _adapter(response={"REQ_FLAG": True, "REQ_DATA": {"userId": "42", "username": "zhangsan"}}).complete_login(
        _jd_provider(),
        _attempt("attempt-1"),
        _callback_context_with_ticket("ticket"),
    )

    assert isinstance(outcome, Authenticated)
    assert outcome.principal.email == "zhangsan@jd.com"
    assert outcome.principal.email_verified is False
```

- [ ] **Step 2: Run JD tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_jd_adapter.py -q`

Expected: FAIL because adapter is missing.

- [ ] **Step 3: Implement JD-specific behavior only in the adapter**

Use `context.cookies.get("sso.jd.com")` for the ticket, validate `userinfo_url`, compute the MD5 protocol signature exactly as required by JD, and return `RestartAuthorization("jd_session_missing")` only when the JD session cookie is absent. Upstream HTTP failures raise `FEDERATION_UPSTREAM_UNAVAILABLE`; `REQ_FLAG=false` raises `FEDERATION_UPSTREAM_DENIED` without embedding `REQ_DATA` or ticket data.

`extract_attempt_id()` must verify the signed correlation cookie; it must not accept a query `state` fallback.

- [ ] **Step 4: Run JD and architecture tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_jd_adapter.py tests/test_identity_federation_architecture.py -q`

Expected: PASS; architecture test confirms the adapter has no auth/database imports.

- [ ] **Step 5: Commit JD adapter**

```bash
git add backend/app/joysafeter_identity_federation/infrastructure/protocols/jd_sso.py backend/tests/test_identity_federation_jd_adapter.py
git commit -m "feat(identity): encapsulate jd sso federation protocol"
```

---

## Batch 3 — Account, Session, and Use-Case Coordination

### Task 10: Extract the Federated Account Gateway and Account Application Service

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/account_gateway.py`
- Create: `backend/app/joysafeter_identity_federation/application/__init__.py`
- Create: `backend/app/joysafeter_identity_federation/application/accounts.py`
- Test: `backend/tests/test_identity_federation_account_gateway.py`

**Interfaces:**
- Consumes: Existing `AuthUser`, `OAuthAccount`, `AuthUserRepository`, and domain account-link policy.
- Produces: `SqlAlchemyFederatedAccountGateway.resolve_or_create()`, `list_accounts()`, `unlink()`, plus `FederatedAccountService.list_accounts()` and `unlink()` for authenticated account-management routes.

- [ ] **Step 1: Write database-backed gateway tests**

Use `db_session` and create explicit users/accounts. Cover existing binding, verified auto-link, unverified collision rejection, registration disabled, registration creation, and last-login-method unlink protection. The security regression must assert:

```python
@pytest.mark.asyncio
async def test_unverified_email_never_links_existing_user(db_session) -> None:
    existing = await _create_user(db_session, email="user@example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email="user@example.com", email_verified=False),
            AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
        )

    assert exc_info.value.code == "FEDERATION_ACCOUNT_LINK_REQUIRED"
    assert await _oauth_binding_count(db_session, existing.id) == 0
```

Add these exact gateway assertions:

```python
@pytest.mark.asyncio
async def test_existing_subject_binding_wins_over_email(db_session) -> None:
    bound_user = await _create_user(db_session, email="bound@example.com", active=True)
    await _create_binding(db_session, bound_user.id, provider="github", subject="subject-1")
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(subject="subject-1", email="different@example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == bound_user.id
    assert resolved.is_new_user is False


@pytest.mark.asyncio
async def test_verified_email_links_active_existing_user(db_session) -> None:
    existing = await _create_user(db_session, email="user@example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(email="User@Example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == existing.id
    assert await _oauth_binding_count(db_session, existing.id) == 1


@pytest.mark.asyncio
async def test_registration_disabled_rejects_unknown_subject(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email="new@example.com", email_verified=True),
            AccountLinkPolicy(allow_registration=False, auto_link_by_email=False),
        )

    assert exc_info.value.code == "FEDERATION_REGISTRATION_DISABLED"


@pytest.mark.asyncio
async def test_registration_preserves_external_email_verification_state(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(email="new@example.com", email_verified=False),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=False),
    )
    user = await AuthUserRepository(db_session).get_by_id(resolved.user_id)

    assert resolved.is_new_user is True
    assert user is not None
    assert user.email_verified is False


@pytest.mark.asyncio
async def test_registration_requires_an_email(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email=None, email_verified=False),
            AccountLinkPolicy(allow_registration=True, auto_link_by_email=False),
        )

    assert exc_info.value.code == "FEDERATION_EMAIL_REQUIRED"


@pytest.mark.asyncio
async def test_subject_binding_race_reloads_the_winning_binding(db_session, monkeypatch) -> None:
    winner = await _create_user(db_session, email="winner@example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)
    monkeypatch.setattr(gateway, "_flush_new_binding", _raise_unique_conflict_after_binding(winner.id))

    resolved = await gateway.resolve_or_create(
        _principal(subject="subject-1", email="winner@example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == winner.id
    assert resolved.is_new_user is False


@pytest.mark.asyncio
async def test_unlink_rejects_only_login_method(db_session) -> None:
    user = await _create_user(db_session, email="sso@example.com", active=True, hashed_password=None)
    await _create_binding(db_session, user.id, provider="jd", subject="42")
    service = FederatedAccountService(SqlAlchemyFederatedAccountGateway(db_session))

    with pytest.raises(FederationError) as exc_info:
        await service.unlink(user.id, ProviderId("jd"))

    assert exc_info.value.code == "FEDERATION_LAST_ACCOUNT_UNLINK_FORBIDDEN"
```

- [ ] **Step 2: Run gateway tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_account_gateway.py -q`

Expected: FAIL because the gateway is missing.

- [ ] **Step 3: Move account responsibilities out of OAuthService**

Implement gateway methods using the existing table and unique index. New users must set:

```python
AuthUser(
    id=str(uuid.uuid4()),
    email=principal.email,
    name=principal.display_name or principal.email.split("@")[0],
    image=principal.avatar_url,
    hashed_password=None,
    email_verified=principal.email_verified,
    is_active=True,
)
```

Do not persist protocol access/refresh tokens. Store only a sanitized claims mapping without `access_token`, `refresh_token`, `id_token`, `code`, `ticket`, or cookies.

Create bindings inside `db_session.begin_nested()` so a `(provider, provider_account_id)` or user-email uniqueness race can roll back to a savepoint without invalidating the outer request transaction. On `IntegrityError`, re-query the winning subject binding first; return it when present, otherwise translate the email collision to `FEDERATION_ACCOUNT_LINK_REQUIRED`.

Implement the application service with an injected commit callable so API routes do not own transactions:

```python
class FederatedAccountService:
    def __init__(self, gateway: FederatedAccountGateway, commit: Callable[[], Awaitable[None]]) -> None:
        self._gateway = gateway
        self._commit = commit

    async def list_accounts(self, user_id: str) -> tuple[FederatedAccountView, ...]:
        return await self._gateway.list_accounts(user_id)

    async def unlink(self, user_id: str, provider_id: ProviderId) -> bool:
        removed = await self._gateway.unlink(user_id, provider_id)
        if removed:
            await self._commit()
        return removed
```

Leave the old `OAuthService` unchanged until Task 15 switches every caller. The new gateway has no old-route caller in this task, so runtime ownership remains singular. Task 17 deletes the old implementation immediately after cutover.

- [ ] **Step 4: Run account tests and existing auth tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_account_gateway.py tests/test_oauth_async_boundary_contract.py -q`

Expected: PASS; the new gateway suite and the still-active old OAuth boundary suite both remain green before API cutover.

- [ ] **Step 5: Commit account boundary**

```bash
git add backend/app/joysafeter_identity_federation/application backend/app/joysafeter_identity_federation/infrastructure/account_gateway.py backend/tests/test_identity_federation_account_gateway.py
git commit -m "refactor(identity): isolate federated account ownership"
```

### Task 11: Add the Auth Session Gateway without Leaking Auth Internals

**Files:**
- Create: `backend/app/joysafeter_identity_federation/infrastructure/session_gateway.py`
- Test: `backend/tests/test_identity_federation_session_gateway.py`
- Modify: `backend/tests/test_identity_federation_architecture.py`

**Interfaces:**
- Consumes: Existing `run_post_login_init()` and `AuthService.issue_login_tokens()` behind one infrastructure adapter.
- Produces: `JoySafeterAuthSessionGateway.issue(user_id, ip_address) -> IssuedAuthSession`.

- [ ] **Step 1: Write failing adapter tests with patched auth services**

```python
@pytest.mark.asyncio
async def test_session_gateway_runs_post_login_then_issues_session(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(session_gateway_module, "run_post_login_init", _record_post_login(calls))
    monkeypatch.setattr(session_gateway_module, "AuthService", _fake_auth_service(calls))
    gateway = JoySafeterAuthSessionGateway(_fake_db(), _fake_user_loader())

    issued = await gateway.issue(user_id="user-1", ip_address="203.0.113.10")

    assert calls == ["load:user-1", "post_login:user-1", "issue:user-1"]
    assert issued.access_token == "access"
    assert issued.refresh_token == "refresh"
    assert issued.csrf_token == "csrf"
```

Add an architecture assertion that no file outside `infrastructure/session_gateway.py` in the federation package imports `joysafeter_auth_service`.

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_session_gateway.py tests/test_identity_federation_architecture.py -q`

Expected: FAIL because the gateway is missing.

- [ ] **Step 3: Implement the narrow auth bridge**

Load the user by ID, raise `FEDERATION_PRINCIPAL_INVALID` if missing/inactive, call `run_post_login_init`, call `AuthService.issue_login_tokens`, and translate the returned dict into `IssuedAuthSession`. Do not import Organization, Project, Member, or ProjectService in the federation package; existing authentication-context provisioning remains encapsulated behind AuthService and requires a separate architecture project.

- [ ] **Step 4: Run session and architecture tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_session_gateway.py tests/test_identity_federation_architecture.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the session gateway**

```bash
git add backend/app/joysafeter_identity_federation/infrastructure/session_gateway.py backend/tests/test_identity_federation_session_gateway.py backend/tests/test_identity_federation_architecture.py
git commit -m "refactor(identity): isolate auth session issuance"
```

### Task 12: Implement Begin-Login Coordination and Callback URL Policy

**Files:**
- Create: `backend/app/joysafeter_identity_federation/application/commands.py`
- Create: `backend/app/joysafeter_identity_federation/application/results.py`
- Create: `backend/app/joysafeter_identity_federation/application/callback_policy.py`
- Create: `backend/app/joysafeter_identity_federation/application/coordinator.py`
- Test: `backend/tests/test_identity_federation_begin_login.py`

**Interfaces:**
- Consumes: Registry, adapter resolver, attempt store, request context, federation settings.
- Produces: `BeginLoginCommand`, `BeginLoginResult`, `CallbackUrlPolicy`, and `FederatedLoginCoordinator.begin_login()`.

- [ ] **Step 1: Write failing begin-login tests**

```python
@pytest.mark.asyncio
async def test_begin_login_creates_one_attempt_and_delegates_to_adapter() -> None:
    store = _RecordingAttemptStore()
    coordinator = _coordinator(store=store, attempt_ids=iter(["attempt-1"]))

    result = await coordinator.begin_login(
        BeginLoginCommand(provider_id="github", callback_url="/managed/dashboard"),
        _request_context(base_url="https://api.example.com"),
    )

    assert result.authorization_url.endswith("state=attempt-1")
    assert len(store.created) == 1
    assert store.created[0].callback_url == "/managed/dashboard"
    assert store.created[0].expires_at - store.created[0].created_at == timedelta(seconds=600)


@pytest.mark.asyncio
async def test_begin_login_rejects_external_callback_url() -> None:
    coordinator = _coordinator()

    with pytest.raises(FederationError) as exc_info:
        await coordinator.begin_login(
            BeginLoginCommand(provider_id="github", callback_url="https://evil.example/steal"),
            _request_context(),
        )

    assert exc_info.value.code == "FEDERATION_CALLBACK_URL_INVALID"


@pytest.mark.parametrize("callback_url", ["//evil.example/path", "/managed\\evil", "/managed\nnext"])
@pytest.mark.asyncio
async def test_begin_login_rejects_ambiguous_relative_callback_urls(callback_url: str) -> None:
    with pytest.raises(FederationError) as exc_info:
        await _coordinator().begin_login(
            BeginLoginCommand(provider_id="github", callback_url=callback_url),
            _request_context(),
        )

    assert exc_info.value.code == "FEDERATION_CALLBACK_URL_INVALID"
```

- [ ] **Step 2: Run begin-login tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_begin_login.py -q`

Expected: FAIL because application modules are missing.

- [ ] **Step 3: Implement one-owner begin flow**

`CallbackUrlPolicy` accepts only relative paths beginning with exactly one `/`, rejects `//`, backslashes, control characters, and absolute URLs, and falls back to the compiled default only when the input is absent.

`begin_login()` must: parse ProviderId; require an active Provider; resolve callback; create a 256-bit URL-safe attempt ID; construct the route-specific redirect URI; call adapter `begin_login`; store the attempt exactly once; return the action. No API or adapter writes Redis directly.

- [ ] **Step 4: Run begin-flow tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_begin_login.py tests/test_identity_federation_state_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit begin-login application flow**

```bash
git add backend/app/joysafeter_identity_federation/application backend/tests/test_identity_federation_begin_login.py
git commit -m "feat(identity): coordinate federation login attempts"
```

### Task 13: Implement Callback Completion, One Retry, and Session Result

**Files:**
- Modify: `backend/app/joysafeter_identity_federation/application/commands.py`
- Modify: `backend/app/joysafeter_identity_federation/application/results.py`
- Modify: `backend/app/joysafeter_identity_federation/application/coordinator.py`
- Test: `backend/tests/test_identity_federation_complete_login.py`

**Interfaces:**
- Consumes: Adapter correlation extraction/completion, atomic attempt store, account gateway, and session gateway.
- Produces: `CompleteLoginCommand`, `LoginSucceeded`, `LoginRestarted`, and `FederatedLoginCoordinator.complete_login()`.

- [ ] **Step 1: Write failing completion matrix tests**

Cover missing attempt, provider mismatch, expiry, authenticated success, session failure propagation, and bounded restart:

```python
@pytest.mark.asyncio
async def test_complete_login_consumes_attempt_before_account_resolution() -> None:
    store = _RecordingAttemptStore(existing=_attempt("attempt-1", provider="github"))
    account_gateway = _RecordingAccountGateway()
    session_gateway = _RecordingSessionGateway()
    coordinator = _coordinator(
        store=store,
        outcome=Authenticated(_principal()),
        account_gateway=account_gateway,
        session_gateway=session_gateway,
    )

    result = await coordinator.complete_login(
        CompleteLoginCommand(provider_id="github"),
        _callback_context(query={"state": "attempt-1", "code": "code-1"}),
    )

    assert store.consumed == ["attempt-1"]
    assert account_gateway.calls == ["resolve_or_create"]
    assert session_gateway.calls == ["issue"]
    assert isinstance(result, LoginSucceeded)


@pytest.mark.parametrize(
    ("stored_attempt", "provider_id", "expected_code"),
    [
        (None, "github", "FEDERATION_ATTEMPT_INVALID"),
        (_attempt("attempt-1", provider="google"), "github", "FEDERATION_ATTEMPT_MISMATCH"),
        (_expired_attempt("attempt-1", provider="github"), "github", "FEDERATION_ATTEMPT_EXPIRED"),
    ],
)
@pytest.mark.asyncio
async def test_complete_login_rejects_invalid_attempts(stored_attempt, provider_id: str, expected_code: str) -> None:
    account_gateway = _RecordingAccountGateway()
    coordinator = _coordinator(
        store=_RecordingAttemptStore(existing=stored_attempt),
        account_gateway=account_gateway,
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id=provider_id),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == expected_code
    assert account_gateway.calls == []


@pytest.mark.asyncio
async def test_session_issue_failure_is_propagated_after_attempt_consumption() -> None:
    store = _RecordingAttemptStore(existing=_attempt("attempt-1", provider="github"))
    coordinator = _coordinator(
        store=store,
        outcome=Authenticated(_principal()),
        account_gateway=_RecordingAccountGateway(),
        session_gateway=_FailingSessionGateway(code="FEDERATION_SESSION_ISSUE_FAILED"),
    )

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(
            CompleteLoginCommand(provider_id="github"),
            _callback_context(query={"state": "attempt-1", "code": "code-1"}),
        )

    assert exc_info.value.code == "FEDERATION_SESSION_ISSUE_FAILED"
    assert store.consumed == ["attempt-1"]


@pytest.mark.asyncio
async def test_jd_restart_is_allowed_once_and_replaces_attempt() -> None:
    consumed = _attempt("attempt-1", provider="jd", retry_count=0)
    coordinator, store = _restart_coordinator(consumed)

    result = await coordinator.complete_login(CompleteLoginCommand(provider_id="jd"), _jd_callback())

    assert isinstance(result, LoginRestarted)
    assert store.replacements[0][0] == consumed
    assert store.replacements[0][1].retry_count == 1


@pytest.mark.asyncio
async def test_second_restart_is_rejected() -> None:
    coordinator, _ = _restart_coordinator(_attempt("attempt-2", provider="jd", retry_count=1))

    with pytest.raises(FederationError) as exc_info:
        await coordinator.complete_login(CompleteLoginCommand(provider_id="jd"), _jd_callback())

    assert exc_info.value.code == "FEDERATION_RETRY_EXHAUSTED"
```

- [ ] **Step 2: Run completion tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_complete_login.py -q`

Expected: FAIL because completion flow is not implemented.

- [ ] **Step 3: Implement completion transaction semantics**

The coordinator must extract the attempt ID through the selected adapter, consume it atomically, validate provider and expiry, call adapter completion, and either create one replacement attempt or resolve/create the account and issue a session.

The account gateway uses flush-only writes. `JoySafeterAuthSessionGateway.issue()` invokes the existing post-login/session issuance boundary, whose durable auth-session path commits. This intentionally makes account creation/linking retry-idempotent if token/session issuance later fails. The coordinator must not claim cross-Redis/SQL atomicity and must not expose SQLAlchemy commit/rollback calls.

`LoginSucceeded` carries only callback URL, access token, refresh token, CSRF token, and expiration values required by the API cookie response. `LoginRestarted` carries a new authorization action and instructs the API to clear the previous correlation cookie before setting a replacement.

- [ ] **Step 4: Run application-flow tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_begin_login.py tests/test_identity_federation_complete_login.py -q`

Expected: PASS.

- [ ] **Step 5: Commit completion coordinator**

```bash
git add backend/app/joysafeter_identity_federation/application backend/tests/test_identity_federation_complete_login.py
git commit -m "feat(identity): coordinate federation callback completion"
```

---

## Batch 4 — API and Frontend Cutover

### Task 14: Expose Runtime/Coordinator Factories from Bootstrap

**Files:**
- Modify: `backend/app/joysafeter_identity_federation/bootstrap.py`
- Test: `backend/tests/test_identity_federation_bootstrap_factory.py`

**Interfaces:**
- Consumes: Compiled configuration, concrete OAuth2/JD adapters, Redis attempt store, signed correlation codec, SQLAlchemy account gateway, and auth session gateway.
- Produces: final `FederationRuntime`, `initialize_identity_federation()`, `get_federation_provider_view()`, `build_federated_login_coordinator(db)`, and `build_federated_account_service(db)`.

- [ ] **Step 1: Write failing factory tests**

Assert the coordinator factory reuses the singleton registry/adapters/store but creates new SQLAlchemy account and auth-session gateway instances for each DB session. Assert provider view returns `providers` in registry order and `login_mode`.

```python
def test_provider_view_exposes_compiled_login_mode(runtime) -> None:
    view = get_federation_provider_view(runtime)

    assert view.login_mode == "redirect"
    assert [provider.id for provider in view.providers] == ["jd"]
```

- [ ] **Step 2: Run factory tests to verify failure**

Run: `cd backend && uv run pytest tests/test_identity_federation_bootstrap_factory.py -q`

Expected: FAIL because factory functions are missing.

- [ ] **Step 3: Implement narrow bootstrap exports**

Populate `ProtocolAdapterRegistry` with `OAuth2Adapter` and `JDSSOAdapter`, build `RedisLoginAttemptStore` from `RedisClient.get_client`, and build `SignedCorrelationCodec` from the application secret. Change API startup from `initialize_identity_federation_configuration()` to final `initialize_identity_federation()` while retaining fail-fast configuration compilation. Do not export concrete config loaders or adapters. API callers receive only application services and immutable public views.

Use this public bootstrap shape:

```python
@dataclass(frozen=True, slots=True)
class FederationRuntime:
    registry: ProviderRegistryPort
    adapters: ProtocolAdapterResolver
    attempt_store: LoginAttemptStore


def initialize_identity_federation(*, force: bool = False) -> FederationRuntime:
    compiled = initialize_identity_federation_configuration(force=force)
    correlation = SignedCorrelationCodec(
        secret=settings.secret_key.encode("utf-8"),
        cookie_name="joysafeter_federation_attempt",
    )
    adapters = ProtocolAdapterRegistry()
    adapters.register(OAuth2Adapter(client_factory=_http_client_factory))
    adapters.register(JDSSOAdapter(correlation=correlation, client_factory=_http_client_factory))
    return _cache_runtime(
        FederationRuntime(
            registry=compiled.registry,
            adapters=adapters,
            attempt_store=RedisLoginAttemptStore(RedisClient.get_client),
        ),
        force=force,
    )


def build_federated_login_coordinator(db: AsyncSession) -> FederatedLoginCoordinator:
    runtime = get_identity_federation_runtime()
    return FederatedLoginCoordinator(
        registry=runtime.registry,
        adapters=runtime.adapters,
        attempt_store=runtime.attempt_store,
        account_gateway=SqlAlchemyFederatedAccountGateway(db),
        session_gateway=JoySafeterAuthSessionGateway(db),
    )


def build_federated_account_service(db: AsyncSession) -> FederatedAccountService:
    return FederatedAccountService(
        gateway=SqlAlchemyFederatedAccountGateway(db),
        commit=db.commit,
    )
```

`get_federation_provider_view()` returns frozen public DTOs with string IDs and `login_mode`; it must not expose client credentials or protocol settings.

- [ ] **Step 4: Run factory/startup tests**

Run: `cd backend && uv run pytest tests/test_identity_federation_bootstrap_factory.py tests/test_identity_federation_startup.py -q`

Expected: PASS.

- [ ] **Step 5: Commit bootstrap factories**

```bash
git add backend/app/joysafeter_identity_federation/bootstrap.py backend/tests/test_identity_federation_bootstrap_factory.py
git commit -m "feat(identity): expose federation application facade"
```

### Task 15: Cut OAuth Routes over to the Federation Application

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/oauth.py:1`
- Replace: `backend/tests/test_oauth_state_fail_closed_contract.py`
- Modify: `backend/tests/test_oauth_async_boundary_contract.py`
- Create: `backend/tests/test_identity_federation_api.py`
- Modify: `backend/tests/test_identity_federation_architecture.py`

**Interfaces:**
- Consumes: Bootstrap application facade, transport-neutral commands/results, current auth-cookie settings.
- Produces: Thin HTTP routes with unchanged paths and response shapes plus `login_mode` on the providers response.

- [ ] **Step 1: Write failing thin-route tests**

Use dependency overrides/monkeypatches to provide fake application services. Assert:

```python
def test_provider_response_contains_login_mode(client, runtime_view) -> None:
    response = client.get("/api/v1/auth/oauth/providers")

    assert response.status_code == 200
    assert response.json() == {
        "providers": [{"id": "jd", "display_name": "JD SSO", "icon": "building"}],
        "login_mode": "redirect",
    }


def test_authorize_route_delegates_without_touching_redis(client, begin_service) -> None:
    response = client.get("/api/v1/auth/oauth/github?callback_url=/managed/dashboard")

    assert response.status_code == 200
    assert response.json()["data"]["authorization_url"].startswith("https://github.com/")
    assert begin_service.commands[0].callback_url == "/managed/dashboard"


def test_callback_restart_redirects_and_replaces_correlation_cookie(client, complete_service) -> None:
    response = client.get("/api/v1/auth/oauth/jd/callback")

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://sso.jd.com/")
    assert "joysafeter_federation_attempt=" in response.headers["set-cookie"]
```

Add success-cookie, provider-denied redirect, invalid-attempt redirect, and account list/unlink route tests.

- [ ] **Step 2: Run API tests against the old routes**

Run: `cd backend && uv run pytest tests/test_identity_federation_api.py -q`

Expected: FAIL because providers lacks `login_mode` and routes still construct Redis/protocol behavior directly.

- [ ] **Step 3: Rewrite `oauth.py` as an HTTP adapter**

Keep Pydantic response models and cookie-writing helpers. Replace all config, protocol, Redis, account, commit, rollback, and JD branches with application calls.

Build `RequestContext`/`CallbackContext` from FastAPI Request. Map `LoginSucceeded` to the existing auth cookies and final callback redirect; map `LoginRestarted` to a 302 authorization redirect; clear `joysafeter_federation_attempt` on success/failure/restart before setting a replacement.

Use this stable boundary mapping:

```python
AUTHORIZE_HTTP_STATUS = {
    "FEDERATION_PROVIDER_NOT_ACTIVE": 404,
    "FEDERATION_CALLBACK_URL_INVALID": 400,
    "FEDERATION_STATE_STORE_UNAVAILABLE": 503,
}

CALLBACK_REDIRECT_CODES = {
    "FEDERATION_ATTEMPT_INVALID": "FEDERATION_ATTEMPT_INVALID",
    "FEDERATION_ATTEMPT_MISMATCH": "FEDERATION_ATTEMPT_MISMATCH",
    "FEDERATION_ATTEMPT_EXPIRED": "FEDERATION_ATTEMPT_EXPIRED",
    "FEDERATION_UPSTREAM_DENIED": "FEDERATION_UPSTREAM_DENIED",
    "FEDERATION_UPSTREAM_UNAVAILABLE": "FEDERATION_UPSTREAM_UNAVAILABLE",
    "FEDERATION_ACCOUNT_LINK_REQUIRED": "FEDERATION_ACCOUNT_LINK_REQUIRED",
    "FEDERATION_REGISTRATION_DISABLED": "FEDERATION_REGISTRATION_DISABLED",
    "FEDERATION_SESSION_ISSUE_FAILED": "FEDERATION_SESSION_ISSUE_FAILED",
}
```

Callback redirects include only the stable error code; do not append exception messages, upstream response bodies, code, ticket, claims, or provider Secret values to the URL.

Replace `_validate_state` tests with attempt-store/coordinator tests already created. Update async-boundary tests to patch the new application facade instead of old protocol handlers.

Add architecture assertions:

```python
assert "RedisClient" not in oauth_source
assert "get_oauth_config" not in oauth_source
assert "get_protocol_handler" not in oauth_source
assert '== "jd_sso"' not in oauth_source
assert "_redirect_to_jd_authorize" not in oauth_source
```

- [ ] **Step 4: Run API, application, and architecture tests**

Run:

```bash
cd backend
uv run pytest tests/test_identity_federation_api.py tests/test_identity_federation_begin_login.py tests/test_identity_federation_complete_login.py tests/test_identity_federation_architecture.py tests/test_oauth_async_boundary_contract.py -q
uv run ruff check app/joysafeter_api/api/v1/oauth.py app/joysafeter_identity_federation tests/test_identity_federation_api.py
```

Expected: PASS.

- [ ] **Step 5: Commit the API cutover**

```bash
git add backend/app/joysafeter_api/api/v1/oauth.py backend/tests/test_oauth_state_fail_closed_contract.py backend/tests/test_oauth_async_boundary_contract.py backend/tests/test_identity_federation_api.py backend/tests/test_identity_federation_architecture.py
git commit -m "refactor(identity): route oauth APIs through federation domain"
```

### Task 16: Make Frontend Login Behavior Follow the Compiled Backend Policy

**Files:**
- Modify: `frontend/components/auth/oauth-buttons.tsx:28`
- Modify: `frontend/app/(auth)/signin/login-form.tsx:38`
- Modify: `frontend/app/(auth)/signin/login-form.test.tsx:330`
- Modify: `frontend/env.example:17`
- Modify: `frontend/README.md:70`

**Interfaces:**
- Consumes: Providers response `{providers, login_mode}`.
- Produces: Chooser mode renders buttons without redirect; redirect mode redirects exactly once to the first active Provider; no frontend Provider-name configuration.

- [ ] **Step 1: Add failing frontend behavior tests**

Extend `login-form.test.tsx`:

```tsx
it('does not auto-redirect in chooser mode', async () => {
  managedGetMock.mockResolvedValueOnce({
    providers: [{ id: 'github', display_name: 'GitHub', icon: 'github' }],
    login_mode: 'chooser',
  })

  render(<LoginForm />)

  await waitFor(() => expect(managedGetMock).toHaveBeenCalledWith('auth/oauth/providers', expect.anything()))
  expect(window.location.href).not.toContain('/auth/oauth/github')
})


it('auto-redirects to the first provider only in redirect mode', async () => {
  managedGetMock
    .mockResolvedValueOnce({
      providers: [{ id: 'jd', display_name: 'JD SSO', icon: 'building' }],
      login_mode: 'redirect',
    })
    .mockResolvedValueOnce({ authorization_url: 'https://sso.jd.com/login' })

  render(<LoginForm />)

  await waitFor(() => expect(managedGetMock).toHaveBeenCalledWith(
    expect.stringContaining('auth/oauth/jd?'),
    expect.anything(),
  ))
})
```

- [ ] **Step 2: Run the focused frontend tests to verify failure**

Run: `cd frontend && bun test app/'(auth)'/signin/login-form.test.tsx`

Expected: chooser test fails because current code redirects whenever a Provider exists.

- [ ] **Step 3: Implement shared response typing and policy-driven redirect**

Add `login_mode: 'chooser' | 'redirect'` to both response types. Change the redirect effect guard to:

```tsx
if (providersResponse.login_mode !== 'redirect') {
  sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
  return
}
```

Keep first-provider selection only after this check. Remove `SSO_DEFAULT_PROVIDER` from frontend env example and README because no runtime code reads it.

- [ ] **Step 4: Run frontend unit, type, and lint checks**

Run:

```bash
cd frontend
bun test app/'(auth)'/signin/login-form.test.tsx
bun run type-check
bun run lint
```

Expected: PASS.

- [ ] **Step 5: Commit frontend policy alignment**

```bash
git add frontend/components/auth/oauth-buttons.tsx frontend/app/'(auth)'/signin/login-form.tsx frontend/app/'(auth)'/signin/login-form.test.tsx frontend/env.example frontend/README.md
git commit -m "fix(identity): make sso redirect follow backend policy"
```

---

## Batch 5 — Remove Compatibility and Complete Deployment Contracts

### Task 17: Delete the Old OAuth Runtime and Rename Deployment Configuration

**Files:**
- Delete: `backend/app/joysafeter_shared/oauth/__init__.py`
- Delete: `backend/app/joysafeter_shared/oauth/config.py`
- Delete: `backend/app/joysafeter_shared/oauth/factory.py`
- Delete: `backend/app/joysafeter_shared/oauth/security.py`
- Delete: `backend/app/joysafeter_shared/oauth/protocols/base.py`
- Delete: `backend/app/joysafeter_shared/oauth/protocols/oauth2.py`
- Delete: `backend/app/joysafeter_shared/oauth/protocols/jd_sso.py`
- Delete: `backend/config/oauth_providers.yaml`
- Delete: `backend/config/oauth_providers.example.yaml`
- Rename: `backend/config/README_OAUTH_LOCAL.md` to `backend/config/README_IDENTITY_FEDERATION_LOCAL.md`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_auth_service.py:925`
- Modify: `backend/app/joysafeter_shared/config/settings.py:633`
- Modify: `backend/env.example:228`
- Modify: `deploy/.env.example:108`
- Modify: `deploy/docker-compose.yml:42`
- Modify: `CHANGELOG.md`
- Test: `backend/tests/test_identity_federation_legacy_removal.py`

**Interfaces:**
- Consumes: New routes and all new federation infrastructure.
- Produces: One runtime path and one deployment vocabulary with no compatibility aliases.

- [ ] **Step 1: Write failing legacy-removal scans**

Create `test_identity_federation_legacy_removal.py`:

```python
LEGACY_TOKENS = (
    "get_oauth_config",
    "OAuthConfigLoader",
    "get_protocol_handler",
    "OAUTH_CONFIG_PATH",
    "SSO_DEFAULT_PROVIDER",
    "JOYSAFETER_ENABLED",
)


def test_legacy_federation_runtime_is_removed() -> None:
    assert not (REPO_ROOT / "backend/app/joysafeter_shared/oauth").exists()
    assert not (REPO_ROOT / "backend/config/oauth_providers.yaml").exists()


@pytest.mark.parametrize("token", LEGACY_TOKENS)
def test_legacy_tokens_are_absent_from_runtime_and_deploy_files(token: str) -> None:
    matches = _search_repository(token)
    assert matches == []
```

Exclude historical docs under `docs/superpowers/specs` and `docs/superpowers/plans` from `_search_repository`; include backend runtime, frontend runtime, deploy files, current config docs, and env examples.

- [ ] **Step 2: Run the scan to verify expected failures**

Run: `cd backend && uv run pytest tests/test_identity_federation_legacy_removal.py -q`

Expected: FAIL with matches in the old package, settings, config files, and env examples.

- [ ] **Step 3: Remove old code and finish deployment vocabulary**

Delete `shared/oauth`; remove the old `OAuthService` section once no callers remain; retain `AuthService` and `run_post_login_init`. Remove `oauth_config_path` from Settings.

Replace backend/deploy examples with:

```dotenv
IDENTITY_FEDERATION_PROVIDERS=
IDENTITY_FEDERATION_CONFIG_PATH=
IDENTITY_FEDERATION_LOGIN_MODE=chooser
```

For the internal JD block in `deploy/.env.example`, use:

```dotenv
IDENTITY_FEDERATION_PROVIDERS=jd
IDENTITY_FEDERATION_LOGIN_MODE=redirect
JD_CLIENT_ID=
JD_CLIENT_SECRET=
JD_AUTHORIZE_URL=
JD_USERINFO_URL=
```

Remove `JD_TOKEN_URL` because the JD adapter does not use it. Add the three federation variables to `x-backend-common-env` in Docker Compose so Compose interpolation and container configuration are explicit.

Rewrite the local federation README to enable `local` with `IDENTITY_FEDERATION_PROVIDERS=local`; do not instruct users to edit `enabled` flags.

- [ ] **Step 4: Run removal, startup, deploy, and documentation checks**

Run:

```bash
cd backend
uv run pytest tests/test_identity_federation_legacy_removal.py tests/test_identity_federation_startup.py tests/test_identity_federation_api.py -q
cd ..
docker compose -f deploy/docker-compose.yml config >/tmp/joysafeter-compose-config.yaml
git diff --check
```

Expected: PASS; Compose config renders successfully; repository scan has zero legacy runtime/config matches.

- [ ] **Step 5: Commit compatibility removal**

```bash
git add -A backend/app/joysafeter_shared/oauth backend/app/joysafeter_domain/services/joysafeter_auth_service.py backend/app/joysafeter_shared/config/settings.py backend/config backend/env.example deploy/.env.example deploy/docker-compose.yml CHANGELOG.md backend/tests/test_identity_federation_legacy_removal.py
git commit -m "refactor(identity): remove legacy oauth compatibility"
```

---

## Batch 6 — System Verification and Preproduction Gate

### Task 18: Run the Full Federation and Deployment Verification Matrix

**Files:**
- Modify only if a verification failure proves a defect in files changed by Tasks 1–17.

**Interfaces:**
- Consumes: Complete federation implementation.
- Produces: Evidence that generic, internal JD, failure, replay, frontend, and Docker build contracts are coherent.

- [ ] **Step 1: Run the complete focused backend suite**

Run:

```bash
cd backend
uv run pytest \
  tests/test_identity_federation_domain.py \
  tests/test_identity_federation_architecture.py \
  tests/test_identity_federation_protocol_registry.py \
  tests/test_identity_federation_config.py \
  tests/test_identity_federation_startup.py \
  tests/test_identity_federation_state_store.py \
  tests/test_identity_federation_correlation.py \
  tests/test_identity_federation_oauth2_adapter.py \
  tests/test_identity_federation_jd_adapter.py \
  tests/test_identity_federation_account_gateway.py \
  tests/test_identity_federation_session_gateway.py \
  tests/test_identity_federation_begin_login.py \
  tests/test_identity_federation_complete_login.py \
  tests/test_identity_federation_bootstrap_factory.py \
  tests/test_identity_federation_api.py \
  tests/test_identity_federation_legacy_removal.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run backend regression and static checks**

Run:

```bash
cd backend
uv run ruff check app tests
uv run pytest -q
```

Expected: PASS. Do not repair unrelated pre-existing failures; record them separately with exact test names and confirm changed-file focused suites remain green.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
cd frontend
bun run test
bun run type-check
bun run lint
bun run build
```

Expected: PASS.

- [ ] **Step 4: Validate deployment/build contracts**

Run:

```bash
docker compose -f deploy/docker-compose.yml config >/tmp/joysafeter-compose-config.yaml
docker build --check -f deploy/docker/backend.Dockerfile backend
docker build --check -f deploy/docker/orchestrator-rs.Dockerfile .
docker build --check -f deploy/docker/orchestrator-rs-jd.Dockerfile .
git diff --check
git status --short
```

Expected: all checks pass and status contains only intended changes.

- [ ] **Step 5: Execute the preproduction configuration matrix**

Run startup/config contract tests for these exact scenarios:

```text
Generic: IDENTITY_FEDERATION_PROVIDERS="", LOGIN_MODE=chooser -> startup succeeds, providers=[]
Invalid generic: providers="", LOGIN_MODE=redirect -> startup fails
Internal JD: providers=jd, LOGIN_MODE=redirect, all JD values present -> startup succeeds, providers=[jd]
Broken JD: providers=jd, missing client_secret and userinfo_url -> startup fails with both issues
Unknown protocol: active or inactive catalog entry uses saml -> startup fails
Redis unavailable: begin-login request -> stable dependency error, no authorization URL
Replay: same attempt callback twice -> first can succeed, second is rejected
JD retry: missing sso.jd.com cookie -> one restart; repeated missing cookie -> rejected
```

Automate these in the focused tests rather than relying on manual observation.

- [ ] **Step 6: Produce the review evidence before any push**

Record:

```text
Focused backend result and count
Full backend result and count
Frontend test/type/lint/build result
Compose and Docker check result
Legacy-token repository scan result
Exact commit list for Batches 0–5
Any unrelated pre-existing failures
```

Do not commit or push verification-only output. If a defect is fixed, rerun the smallest failing test, the owning batch suite, and the full focused suite before creating a narrowly scoped fix commit.

# LLM Engine/Protocol/Provider Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:using-git-worktrees` before implementation, then use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Apply `superpowers:test-driven-development` per task and `superpowers:verification-before-completion` before reporting success.

**Goal:** Establish a new-system LLM domain baseline in which Engine capabilities, Provider bindings, Secret persistence, Agent selection, Quickstart, and runtime credential routing all use one explicit Protocol-based contract.

**Architecture:** A version-controlled backend Catalog defines Engines, Protocols, Provider/Protocol bindings, and Credential Profiles. Python loads and validates the Catalog, owns management-plane filtering and validation, and exposes it through an authenticated API. Secret persistence stores explicit `kind + provider + protocol`; the frontend consumes the Catalog and server-filtered Secret lists; Rust validates the same metadata before decrypting or injecting credentials.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL/SQLite tests, PyYAML, React 19, Next.js 16, TanStack Query, Vitest, Rust 2021, serde/serde_yaml.

## Global Constraints

- This is a new system. Do not add data conversion, Provider aliases, request-field fallbacks, compatibility windows, or key-based identity detection.
- Modify `backend/alembic/versions/20260803_000001_initial_schema.py` directly. Do not create another Alembic revision.
- `kind` is required from the first schema and every Secret create request.
- LLM Secret requires Catalog-valid `provider + protocol`; Generic Secret requires both fields to be null.
- `kind`, `provider`, and `protocol` are immutable after Secret creation; changing identity requires a new Secret and an explicit Agent reference update.
- Reject every Catalog Engine ID as a Secret Provider value, and reject Catalogs whose Engine and Provider ID namespaces overlap.
- Agent creation requires an explicit `engine_kind`; frontend and API must not guess or default an Engine.
- Secret must not persist `engine_kind`; an Engine selected during Secret creation is only a UI/query filter.
- Compatibility is valid only when the selected Protocol is supported by both the Engine and Provider binding.
- Backend filtering and validation are authoritative; frontend helpers are presentation logic only.
- Rust must validate Secret metadata before decrypting `data` or constructing sandbox input.
- Initial Engine matrix: Claude → `anthropic_messages`; Codex → `openai_responses`; Native and Pi → all three initial Protocols.
- Initial Providers: Anthropic, OpenAI, DeepSeek, and Custom.
- Agent and Quickstart inline Secret creation must stay in the current flow and must not open nested dialogs.
- Changing Engine must never silently substitute a different production Secret.
- Raw environment variable keys remain under advanced settings; normal labels use “模型服务商”“API 协议”“访问凭据”.
- Do not touch unrelated dirty files and do not create commits unless the user explicitly requests them.

## Canonical Interfaces

### Catalog Models

```python
class CredentialField(BaseModel):
    key: str
    label: str
    type: Literal["secret", "text", "url", "select"]
    required: bool = False
    placeholder: str | None = None
    help_text: str | None = None
    options: list[str] = Field(default_factory=list)
    advanced: bool = False


class CredentialProfile(BaseModel):
    id: str
    fields: list[CredentialField]
    required_any_of: list[list[str]] = Field(default_factory=list)
    base_url_key: str | None = None
    model_key: str | None = None


class ProviderProtocolBinding(BaseModel):
    protocol_id: str
    credential_profile_id: str
    default_base_url: str | None = None
    model_suggestions: list[str] = Field(default_factory=list)


class EngineCapability(BaseModel):
    id: str
    display_name: str
    enabled: bool = True
    supported_protocol_ids: list[str]
    preferred_protocol_ids: list[str] = Field(default_factory=list)


class ProtocolDefinition(BaseModel):
    id: str
    display_name: str
    description: str


class ProviderDefinition(BaseModel):
    id: str
    display_name: str
    enabled: bool = True
    protocol_bindings: list[ProviderProtocolBinding]


class LlmCatalog(BaseModel):
    version: str
    engines: list[EngineCapability]
    protocols: list[ProtocolDefinition]
    providers: list[ProviderDefinition]
    credential_profiles: list[CredentialProfile]
```

### Compatibility Functions

```python
def compatible_protocol_ids(engine_id: str, provider_id: str | None = None) -> list[str]: ...

def compatible_provider_protocol_pairs(engine_id: str) -> list[tuple[str, str]]: ...

def compatible_engine_ids(provider_id: str, protocol_id: str) -> list[str]: ...

def validate_provider_protocol(provider_id: str, protocol_id: str) -> ProviderProtocolBinding: ...

def validate_engine_protocol(engine_id: str, protocol_id: str) -> None: ...

def validate_credential_data(provider_id: str, protocol_id: str, data: Mapping[str, str]) -> None: ...
```

All returned lists preserve Catalog order. Unknown IDs and invalid relationships raise typed `LlmCompatibilityError` with stable error codes and metadata-only `data`.

### Secret Persistence Contract

```text
kind = llm     => provider != null, protocol != null
kind = generic => provider == null, protocol == null, is_default == false
```

Protocol defaults are unique per scope:

```text
global:  unique(protocol) where project_id is null and kind = llm and is_default and not deleted
project: unique(project_id, protocol) where project_id is not null and kind = llm and is_default and not deleted
```

### Frontend Form Contract

```typescript
type LlmSecretFormValues = Record<string, string>

type LlmSecretConfiguratorProps = {
  initialEngineId?: string
  showEngineSelector?: boolean
  onCancel: () => void
  onCreated: (secret: SecretListItem) => void
}

export function stableConnectionFingerprint(input: {
  providerId: string
  protocolId: string
  values: LlmSecretFormValues
}): string {
  const values = Object.fromEntries(
    Object.entries(input.values).sort(([left], [right]) => left.localeCompare(right)),
  )
  return JSON.stringify({
    providerId: input.providerId,
    protocolId: input.protocolId,
    values,
  })
}
```

The fingerprint exists only in component memory for stale-test detection. Never write it to logs, storage, telemetry, query parameters, or error payloads.

## File Structure

### New Backend Files

- `backend/config/llm_catalog.yaml`
- `backend/app/joysafeter_domain/llm/__init__.py`
- `backend/app/joysafeter_domain/llm/catalog.py`
- `backend/app/joysafeter_domain/llm/compatibility.py`
- `backend/app/joysafeter_domain/schemas/joysafeter_llm.py`
- `backend/app/joysafeter_api/api/v1/llm.py`
- `backend/tests/test_llm_catalog.py`
- `backend/tests/test_llm_catalog_api.py`
- `backend/tests/test_llm_secret_schema.py`
- `backend/tests/test_llm_secret_catalog.py`
- `backend/tests/test_llm_agent_compatibility.py`
- `backend/tests/test_llm_quickstart_compatibility.py`
- `backend/tests/test_llm_runtime_catalog_contract.py`

### Modified Backend Files

- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/alembic/versions/20260803_000001_initial_schema.py`
- `backend/app/joysafeter_shared/runtime/lifecycle.py`
- `backend/app/joysafeter_api/api/v1/router.py`
- `backend/app/joysafeter_domain/models/joysafeter_secret.py`
- `backend/app/joysafeter_domain/schemas/joysafeter_secret.py`
- `backend/app/joysafeter_domain/services/joysafeter_secret_service.py`
- `backend/app/joysafeter_api/api/v1/secrets.py`
- `backend/app/joysafeter_api/api/v1/agents.py`
- `backend/app/joysafeter_api/api/v1/quickstart.py`
- `backend/tests/test_secret_connectivity.py`
- `backend/tests/test_secret_lifecycle_active_dependencies.py`
- `backend/tests/test_agent_environment_ref_validation.py`

### Modified Rust Files

- `backend/app/joysafeter_orchestrator_rs/Cargo.toml`
- `backend/app/joysafeter_orchestrator_rs/Cargo.lock`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/mod.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/llm_catalog.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/llm_providers.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`

### New Frontend Files

- `frontend/types/llm.ts`
- `frontend/lib/managed/llm-catalog.ts`
- `frontend/lib/managed/llm-catalog.test.ts`
- `frontend/hooks/managed/use-llm-catalog.ts`
- `frontend/hooks/managed/use-compatible-secrets.ts`
- `frontend/hooks/managed/use-compatible-secrets.test.tsx`
- `frontend/lib/managed/secret-query-keys.ts`
- `frontend/lib/managed/secret-query-keys.test.ts`
- `frontend/lib/managed/quickstart-input-state.ts`
- `frontend/lib/managed/quickstart-input-state.test.ts`
- `frontend/components/managed/llm/llm-secret-configurator.tsx`
- `frontend/components/managed/llm/llm-secret-configurator.test.tsx`
- `frontend/components/managed/llm/compatible-secret-picker.tsx`
- `frontend/components/managed/llm/compatible-secret-picker.test.tsx`
- `frontend/components/managed/llm/llm-catalog-page-state.tsx`
- `frontend/components/managed/llm/llm-catalog-page-state.test.tsx`
- `frontend/components/managed/shared/compatible-engine-badges.tsx`
- `frontend/app/managed/secrets/components/create-secret-dialog.tsx`
- `frontend/app/managed/secrets/components/create-secret-dialog.test.tsx`
- `frontend/app/managed/agents/components/agent-secret-selection.test.tsx`
- `frontend/app/managed/agents/[agentId]/edit/page.test.tsx`

### Modified Frontend Files

- `frontend/lib/api-client.ts`
- `frontend/lib/managed/secret-response-parsers.ts`
- `frontend/lib/managed/secret-response-parsers.test.ts`
- `frontend/lib/managed/agent-response-parsers.ts`
- `frontend/lib/managed/agent-response-parsers.test.ts`
- `frontend/hooks/managed/use-paginated-list.ts`
- `frontend/hooks/managed/use-paginated-list.test.tsx`
- `frontend/hooks/managed/use-quickstart-chat.ts`
- `frontend/hooks/managed/use-quickstart-chat.test.tsx`
- `frontend/app/managed/secrets/page.tsx`
- `frontend/app/managed/secrets/[secretId]/page.tsx`
- `frontend/app/managed/agents/components/create-agent-dialog.tsx`
- `frontend/app/managed/agents/components/create-agent-dialog.test.tsx`
- `frontend/app/managed/agents/[agentId]/edit/page.tsx`
- `frontend/app/managed/quickstart/page.tsx`
- `frontend/lib/managed/quickstart-create.ts`
- `frontend/lib/managed/quickstart-create.test.ts`
- `frontend/lib/i18n/locales/en.ts`
- `frontend/lib/i18n/locales/zh.ts`
- `docs/api/openapi.md`
- `docs/tutorials/01-model-provider-setup.md`
- `docs/tutorials/04-agent-build-and-run.md`

### Removed Frontend File

- `frontend/app/managed/agents/components/model-secret-select.tsx` after all callers use `CompatibleSecretPicker`.

---

## Task 1: Build the Canonical LLM Catalog

**Files:**
- Create `backend/config/llm_catalog.yaml`
- Create `backend/app/joysafeter_domain/llm/__init__.py`
- Create `backend/app/joysafeter_domain/llm/catalog.py`
- Create `backend/tests/test_llm_catalog.py`
- Modify `backend/pyproject.toml`
- Modify `backend/uv.lock`

### Step 1: Write failing Catalog tests

Cover:

- Exact initial Engine matrix.
- Exact initial Provider bindings.
- Duplicate IDs.
- Missing Protocol/Profile references.
- Duplicate Provider/Protocol binding.
- Preferred Protocol outside supported Protocols.
- Invalid `required_any_of`, `base_url_key`, and `model_key` references.
- Catalog order preservation.

Run:

```bash
cd backend
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run pytest tests/test_llm_catalog.py -v
```

Expected RED: Catalog module does not exist.

### Step 2: Add the initial YAML

Define three Protocols, four Engines, four Providers, and two Credential Profiles.

```yaml
version: "2026-08-07.1"
protocols:
  - id: anthropic_messages
    display_name: Anthropic Messages API
    description: Anthropic Messages request and stream contract
  - id: openai_responses
    display_name: OpenAI Responses API
    description: OpenAI Responses request and event stream contract
  - id: chat_completions
    display_name: Chat Completions API
    description: OpenAI-compatible Chat Completions contract
engines:
  - id: claude
    display_name: Claude Code
    supported_protocol_ids: [anthropic_messages]
    preferred_protocol_ids: [anthropic_messages]
  - id: codex
    display_name: Codex
    supported_protocol_ids: [openai_responses]
    preferred_protocol_ids: [openai_responses]
  - id: native
    display_name: Native
    supported_protocol_ids: [anthropic_messages, openai_responses, chat_completions]
    preferred_protocol_ids: [anthropic_messages, openai_responses, chat_completions]
  - id: pi
    display_name: Pi
    supported_protocol_ids: [anthropic_messages, openai_responses, chat_completions]
    preferred_protocol_ids: [chat_completions, anthropic_messages, openai_responses]
```

Profiles:

- `anthropic_standard`: `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; optional `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`; `base_url_key=ANTHROPIC_BASE_URL`; `model_key=ANTHROPIC_MODEL`.
- `openai_bearer`: required `OPENAI_API_KEY`; optional `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`; `base_url_key=OPENAI_BASE_URL`; `model_key=OPENAI_MODEL`.

Bindings:

- Anthropic → Anthropic Messages → `anthropic_standard`.
- OpenAI → Responses and Chat Completions → `openai_bearer`.
- DeepSeek → Chat Completions → `openai_bearer`, default Base URL `https://api.deepseek.com`.
- Custom → all Protocols, using the Protocol-appropriate profile and no default Base URL.

### Step 3: Add the direct YAML dependency

Add `PyYAML>=6.0` to the main project dependencies and update `backend/uv.lock`. Do not rely on another package to install YAML support transitively.

### Step 4: Implement strict loading

- Use `yaml.safe_load`.
- Set `ConfigDict(extra="forbid")` on Catalog models.
- Resolve Catalog path relative to backend package/config, not process CWD.
- Cache `get_llm_catalog()` with `@lru_cache(maxsize=1)`.
- Add lookup methods that raise `LlmCatalogError`, never return `None` for unknown IDs.

### Step 5: Run tests

Run the Task 1 command and require GREEN.

---

## Task 2: Add Compatibility Service, Startup Validation, and Catalog API

**Files:**
- Create `backend/app/joysafeter_domain/llm/compatibility.py`
- Create `backend/app/joysafeter_domain/schemas/joysafeter_llm.py`
- Create `backend/app/joysafeter_api/api/v1/llm.py`
- Modify `backend/app/joysafeter_shared/runtime/lifecycle.py`
- Modify `backend/app/joysafeter_api/api/v1/router.py`
- Create `backend/tests/test_llm_catalog_api.py`
- Create `backend/tests/test_llm_runtime_catalog_contract.py`

### Step 1: Extend tests for compatibility helpers

Add to `test_llm_catalog.py`:

```python
assert compatible_protocol_ids("codex") == ["openai_responses"]
assert compatible_protocol_ids("native", "openai") == [
    "openai_responses",
    "chat_completions",
]
assert compatible_provider_protocol_pairs("claude") == [
    ("anthropic", "anthropic_messages"),
    ("custom", "anthropic_messages"),
]
assert compatible_engine_ids("deepseek", "chat_completions") == ["native", "pi"]
```

Verify missing credentials raise `LLM_SECRET_CREDENTIALS_INCOMPLETE`, while either Anthropic alternative satisfies `required_any_of`.

### Step 2: Implement typed errors and pure functions

`compatible_provider_protocol_pairs(engine_id)` must iterate Provider definitions in Catalog order and each Provider's bindings in binding order, including only bindings supported by the Engine.

Credential validation must inspect keys only after Provider and Protocol are already known. It must never select Provider or Protocol from keys.

### Step 3: Add startup fail-fast

Call `get_llm_catalog()` from `_run_common_startup()` immediately after credential encryption configuration validation. A malformed Catalog must stop API and worker startup with a clear configuration error.

### Step 4: Write and implement Catalog API tests

Test authenticated `GET /api/v1/llm/catalog`:

- Returns exact response fields.
- Codex exposes only `openai_responses`.
- Credential metadata contains no Secret values.
- `ETag` is the quoted Catalog version.
- `Cache-Control` is short-lived and private.
- Route requires read context, not write permission.

Mount `llm_router` at `/llm`.

### Step 5: Add management/data-plane identifier contract test

Assert active bindings use only Credential Profile IDs implemented by Rust: `anthropic_standard` and `openai_bearer`.

### Step 6: Run tests

```bash
cd backend
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_llm_catalog.py \
  tests/test_llm_catalog_api.py \
  tests/test_llm_runtime_catalog_contract.py \
  tests/test_read_route_dependency_contract.py -v
```

---

## Task 3: Establish the Initial Secret Schema

**Files:**
- Modify `backend/alembic/versions/20260803_000001_initial_schema.py`
- Modify `backend/app/joysafeter_domain/models/joysafeter_secret.py`
- Modify `backend/app/joysafeter_domain/schemas/joysafeter_secret.py`
- Create `backend/tests/test_llm_secret_schema.py`
- Modify `backend/tests/test_secret_lifecycle_active_dependencies.py`

### Step 1: Write failing schema tests

Test:

- `kind` is required and accepts only `llm` or `generic`.
- LLM create requires Provider and Protocol.
- Generic create rejects Provider, Protocol, and `is_default=true`.
- Response models expose nullable Provider/Protocol and required kind.
- SQLAlchemy metadata includes the kind/identity check constraint.
- SQLAlchemy metadata includes project and global Protocol-default indexes.

### Step 2: Change the initial Alembic baseline

Replace current defaults with:

```python
sa.Column("kind", sa.String(length=16), nullable=False),
sa.Column("provider", sa.String(length=64), nullable=True),
sa.Column("protocol", sa.String(length=64), nullable=True),
```

Add a check constraint equivalent to:

```sql
(kind = 'llm' AND provider IS NOT NULL AND protocol IS NOT NULL)
OR
(kind = 'generic' AND provider IS NULL AND protocol IS NULL AND is_default = false)
```

Add separate partial unique indexes for project and global Protocol defaults. Keep the revision ID and head unchanged.

### Step 3: Align SQLAlchemy and Pydantic

- Add `SecretKind(StrEnum)` with `LLM="llm"`, `GENERIC="generic"`.
- Make `CreateSecretRequest.kind` required.
- Make Provider/Protocol optional fields without defaults.
- Add a model validator for the `kind` invariants.
- Remove Provider/Protocol from `UpdateSecretRequest`; set `ConfigDict(extra="forbid")` so identity-changing fields are rejected.
- Add `kind` to list/detail responses.
- Keep Secret values trimming behavior.
- Do not add any request normalization or inferred defaults.

### Step 4: Verify the single head

```bash
cd backend
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_llm_secret_schema.py \
  tests/test_secret_lifecycle_active_dependencies.py -v
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run alembic heads
```

Expected Alembic output: only `20260803_000001 (head)`.

---

## Task 4: Make Secret Service and API Catalog-Driven

**Files:**
- Modify `backend/app/joysafeter_domain/services/joysafeter_secret_service.py`
- Modify `backend/app/joysafeter_api/api/v1/secrets.py`
- Create `backend/tests/test_llm_secret_catalog.py`
- Modify `backend/tests/test_secret_connectivity.py`

### Step 1: Write failing service/API tests

Cover:

- Valid LLM Secret creation.
- Update requests reject `kind`, Provider, and Protocol changes.
- LLM update validates the final merged plaintext and rejects removal of required credentials.
- Masked unchanged values preserve the existing credential during update validation.
- Unknown Provider or Protocol.
- Invalid Provider/Protocol binding.
- Reserved Engine names used as Provider.
- Generic Secret validation.
- `compatible_engine` filtering before pagination.
- Provider and Protocol filters combined with Engine filtering.
- Unknown filter IDs return typed errors.
- `compatible_engine_ids` in list/detail responses.
- Protocol-scoped default clearing.
- Connection test routing by explicit Provider/Protocol binding.

### Step 2: Centralize Secret validation

Before encryption and persistence:

```python
if req.kind is SecretKind.LLM:
    validate_provider_protocol(req.provider, req.protocol)
    validate_credential_data(req.provider, req.protocol, req.data)
else:
    assert req.provider is None and req.protocol is None
```

Reject reserved Provider IDs before Catalog lookup with `LLM_SECRET_PROVIDER_RESERVED`.

Secret update only replaces `data` and other explicitly allowed non-identity fields. It never changes `kind`, Provider, or Protocol.

For LLM updates, build the final plaintext before encryption:

1. Decrypt the existing data in the service boundary.
2. Replace masked unchanged fields with the existing plaintext value.
3. Apply requested additions/removals.
4. Validate the final plaintext using the persisted Provider/Protocol binding.
5. Encrypt the validated result for storage.

Do not treat a mask such as `********` as a new credential value.

### Step 3: Implement Protocol-scoped defaults

Change service signatures to require Protocol for LLM default operations:

```python
async def get_default_secret(*, project_id: str | None, protocol: str) -> JoySafeterSecret | None: ...

async def clear_default_secret(*, project_id: str | None, protocol: str) -> None: ...
```

Generic Secret never enters either method.

### Step 4: Implement filters before pagination

Add API query parameters:

```text
kind
provider
protocol
compatible_engine
```

For Engine filtering:

```python
pairs = compatible_provider_protocol_pairs(compatible_engine)
predicate = tuple_(JoySafeterSecret.provider, JoySafeterSecret.protocol).in_(pairs)
```

Apply all predicates to the SQL query before cursor/limit. Never load a page and filter it in Python.

### Step 5: Replace connectivity dispatch

- Call `validate_provider_protocol` and `validate_credential_data` first.
- Resolve `CredentialProfile.base_url_key` and Provider binding `default_base_url`.
- Choose the HTTP request adapter from `protocol`, not Provider aliases or credential keys.
- Use `CredentialProfile.model_key` for the model field.
- Preserve SSRF/base URL validation and bounded upstream error details.

### Step 6: Run tests

```bash
cd backend
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_llm_secret_catalog.py \
  tests/test_secret_connectivity.py \
  tests/test_secret_lifecycle_active_dependencies.py -v
```

---

## Task 5: Enforce Agent and Quickstart Compatibility

**Files:**
- Modify `backend/app/joysafeter_api/api/v1/agents.py`
- Modify `backend/app/joysafeter_api/api/v1/quickstart.py`
- Create `backend/tests/test_llm_agent_compatibility.py`
- Create `backend/tests/test_llm_quickstart_compatibility.py`
- Modify `backend/tests/test_agent_environment_ref_validation.py`

### Step 1: Write failing Agent tests

Assert:

- Claude accepts Anthropic Messages Secret and rejects Responses Secret.
- Codex accepts Responses Secret and rejects Chat Completions Secret.
- Native/Pi accept each declared Protocol.
- Generic Secret cannot be used as Agent model configuration.
- Same Secret can be used by multiple compatible Engines.
- Errors contain Engine/Provider/Protocol metadata but no Secret values.

### Step 2: Replace Agent heuristics

Delete `_secret_matches_engine` and replace it with one validator:

```python
async def validate_agent_secret_ref(
    *,
    engine_kind: str,
    secret_ref: str,
    project_id: str | None,
    secret_svc: SecretService,
) -> JoySafeterSecret:
    secret = await secret_svc.get_secret_by_name(secret_ref, project_id=project_id)
    # existence, kind, provider/protocol binding, engine/protocol
    return secret
```

Use it for Agent create and update.

This validator reads metadata only and must not decrypt `secret.data`. Credential completeness is enforced when the Secret is created or updated.

### Step 3: Resolve model through Credential Profile

Replace engine-specific key selection with:

```python
binding = validate_provider_protocol(secret.provider, secret.protocol)
profile = catalog.credential_profile(binding.credential_profile_id)
model_id = secret_data.get(profile.model_key) if profile.model_key else None
```

Do not fall back to `MODEL` or inspect unrelated keys.

### Step 4: Change Quickstart request contract

Replace `QuickstartChatRequest.provider` with required `engine_kind`. Set `ConfigDict(extra="forbid")` so old field names are rejected instead of interpreted.

Quickstart must:

1. Load Secret by `secret_ref`.
2. Apply the same Agent validator.
3. Select streaming adapter by Secret Protocol.
4. Resolve Base URL/model/credentials from the Provider binding and Credential Profile.

### Step 5: Run tests

```bash
cd backend
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_llm_agent_compatibility.py \
  tests/test_llm_quickstart_compatibility.py \
  tests/test_agent_environment_ref_validation.py \
  tests/test_quickstart_error_contract.py -v
```

---

## Task 6: Enforce the Catalog in Rust Before Decryption

**Files:**
- Modify `backend/app/joysafeter_orchestrator_rs/Cargo.toml`
- Modify `backend/app/joysafeter_orchestrator_rs/Cargo.lock`
- Modify `backend/app/joysafeter_orchestrator_rs/src/kernel/mod.rs`
- Create `backend/app/joysafeter_orchestrator_rs/src/kernel/llm_catalog.rs`
- Modify `backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs`
- Modify `backend/app/joysafeter_orchestrator_rs/src/kernel/llm_providers.rs`
- Modify `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`

### Step 1: Write failing Rust contract tests

Test:

- The embedded YAML parses.
- Rust Engine declarations exactly match Catalog Protocol IDs.
- Every active Credential Profile has a routing implementation.
- Valid Engine/Secret pairs succeed.
- Invalid kind, Provider/Protocol, and Engine/Protocol pairs fail.
- Validation errors contain no Secret data.

### Step 2: Add the runtime Catalog module

- Add `serde_yaml`.
- Embed the canonical backend YAML with `include_str!`.
- Deserialize only fields required by the data plane.
- Expose:

```rust
pub fn validate_runtime_secret(
    engine_kind: &str,
    kind: &str,
    provider: Option<&str>,
    protocol: Option<&str>,
) -> Result<RuntimeSecretBinding, LlmCatalogError>
```

`RuntimeSecretBinding` contains resolved Protocol, Credential Profile ID, default Base URL, base URL key, and model key.

### Step 3: Validate before decrypting

Change both Secret-resolution SQL queries to select `kind, provider, protocol, data`. Call `validate_runtime_secret` before decrypting or merging `data`.

### Step 4: Route by Profile and Protocol

- `anthropic_standard` maps to Anthropic credential injection.
- `openai_bearer` maps to OpenAI-compatible credential injection.
- Protocol selects request/harness semantics.
- Provider binding supplies default Base URL only when the Secret has no explicit Base URL.

### Step 5: Run Rust tests

```bash
cd backend/app/joysafeter_orchestrator_rs
cargo test llm_catalog
cargo test llm_providers
cargo test harness_input_builder
cargo test sandbox_resolver
```

---

## Task 7: Add Frontend Catalog Client and Compatible Secret Hook

**Files:**
- Create `frontend/types/llm.ts`
- Create `frontend/lib/managed/llm-catalog.ts`
- Create `frontend/lib/managed/llm-catalog.test.ts`
- Create `frontend/hooks/managed/use-llm-catalog.ts`
- Create `frontend/hooks/managed/use-compatible-secrets.ts`
- Create `frontend/hooks/managed/use-compatible-secrets.test.tsx`
- Modify `frontend/lib/api-client.ts`
- Modify `frontend/lib/managed/secret-response-parsers.ts`
- Modify `frontend/lib/managed/secret-response-parsers.test.ts`

### Step 1: Write failing parser/helper tests

Cover:

- Strict Catalog response parsing.
- Provider/Protocol options for each Engine.
- Catalog order preservation.
- Unknown references rejected.
- `stableConnectionFingerprint` is stable across object key order and changes when Provider, Protocol, or any value changes.
- Secret parsing includes `kind`, nullable Provider/Protocol, model summary, default flag, and compatible Engine IDs.

### Step 2: Implement pure frontend helpers

Expose:

```typescript
getEngine(catalog, engineId)
getProvider(catalog, providerId)
getProtocol(catalog, protocolId)
getCredentialProfileForBinding(catalog, providerId, protocolId)
getProviderProtocolOptions(catalog, engineId)
stableConnectionFingerprint(input)
```

These helpers do not decide whether a persisted Secret is compatible; that list comes from the server.

### Step 3: Implement Catalog query

Use one stable query key:

```typescript
['llm-catalog']
```

Respect API errors, keep the previous Catalog during background refresh, and never render an empty Catalog as success.

### Step 4: Implement compatible Secret query

```typescript
useCompatibleSecrets({ engineId, enabled })
```

- Request `kind=llm&compatible_engine=<engineId>`.
- Follow the existing cursor contract until all options needed by the picker are loaded.
- Keep loading, error, retry, and genuine-empty states distinct.
- Query key includes project scope and Engine.

### Step 5: Run tests

```bash
cd frontend
bun run test -- \
  lib/managed/llm-catalog.test.ts \
  hooks/managed/use-compatible-secrets.test.tsx \
  lib/managed/secret-response-parsers.test.ts
bun run type-check
```

---

## Task 8: Build the Shared Secret Configuration Experience

**Files:**
- Create `frontend/components/managed/llm/llm-secret-configurator.tsx`
- Create `frontend/components/managed/llm/llm-secret-configurator.test.tsx`
- Create `frontend/components/managed/llm/compatible-secret-picker.tsx`
- Create `frontend/components/managed/llm/compatible-secret-picker.test.tsx`
- Create `frontend/components/managed/shared/compatible-engine-badges.tsx`
- Create `frontend/app/managed/secrets/components/create-secret-dialog.tsx`
- Create `frontend/app/managed/secrets/components/create-secret-dialog.test.tsx`
- Modify `frontend/app/managed/secrets/page.tsx`
- Modify `frontend/app/managed/secrets/[secretId]/page.tsx`
- Modify `frontend/lib/i18n/locales/en.ts`
- Modify `frontend/lib/i18n/locales/zh.ts`

### Step 1: Write failing configurator tests

Test:

- Engine filters Provider/Protocol combinations.
- One Protocol auto-selects and hides the Protocol control.
- Multiple Protocols display a selector with descriptions.
- Changing Engine preserves a still-valid pair and clears an invalid pair.
- Changing Provider/Protocol removes values not present in the next Credential Profile.
- `required_any_of` displays one clear validation error.
- Raw keys are hidden until advanced settings open.
- Successful test becomes stale after any fingerprint input changes.
- Failed test/create keeps values and offers retry.
- Keyboard focus and mobile single-column behavior remain usable.

### Step 2: Implement `LlmSecretConfigurator`

Required local state:

```typescript
const [engineId, setEngineId] = useState(initialEngineId ?? '')
const [providerId, setProviderId] = useState('')
const [protocolId, setProtocolId] = useState('')
const [values, setValues] = useState<Record<string, string>>({})
const [testedFingerprint, setTestedFingerprint] = useState<string | null>(null)
```

Derive:

```typescript
const currentFingerprint = stableConnectionFingerprint({ providerId, protocolId, values })
const connectionTestIsFresh = testedFingerprint === currentFingerprint
```

When Profile changes, rebuild `values` from the new Profile's field keys; never leave hidden credentials from the previous Profile in submit state.

### Step 3: Implement connection test and create

- Send explicit `kind: 'llm'`, Provider, Protocol, and current values.
- Disable duplicate submissions but keep fields readable.
- Mark test fresh only after a successful response for the exact current fingerprint.
- Creating does not require a successful connection test unless product policy later makes that explicit.
- Invoke `onCreated` with the newly returned Secret.

### Step 4: Implement `CompatibleSecretPicker`

Props include `engineId`, `value`, `onChange`, `onCreateRequested`, `disabled`, and optional conflict metadata. Render Provider, Protocol, model, and default marker without rendering credential keys.

### Step 5: Refactor Secret pages

- Default create choice is LLM model configuration; Generic Secret remains available as a separate choice.
- Optional Engine context is labeled “仅用于筛选兼容配置，不会绑定到该引擎”.
- Read optional `engine` query parameter for entry from other screens.
- List/detail views show `kind`, Provider, Protocol, default status, and compatible Engine badges.
- Keep pagination, delete, and default actions in the page shell.

### Step 6: Run tests

```bash
cd frontend
bun run test -- \
  components/managed/llm/llm-secret-configurator.test.tsx \
  components/managed/llm/compatible-secret-picker.test.tsx \
  app/managed/secrets/components/create-secret-dialog.test.tsx
bun run type-check
```

---

## Task 9: Refactor Agent and Quickstart Flows

**Files:**
- Modify `frontend/app/managed/agents/components/create-agent-dialog.tsx`
- Modify `frontend/app/managed/agents/components/create-agent-dialog.test.tsx`
- Create `frontend/app/managed/agents/components/agent-secret-selection.test.tsx`
- Modify `frontend/app/managed/agents/[agentId]/edit/page.tsx`
- Create `frontend/app/managed/agents/[agentId]/edit/page.test.tsx`
- Remove `frontend/app/managed/agents/components/model-secret-select.tsx`
- Modify `frontend/app/managed/quickstart/page.tsx`
- Modify `frontend/lib/managed/quickstart-create.ts`
- Modify `frontend/lib/managed/quickstart-create.test.ts`

### Step 1: Write failing Agent create tests

Assert:

- Secret request includes selected Engine.
- Only server-returned compatible Secrets render.
- One option or unique Protocol default may auto-select initially.
- Engine change preserves compatible selection.
- Engine change clears incompatible selection with visible copy and does not choose a replacement.
- “创建模型配置” switches the same Dialog to a configurator subview without losing Agent draft state.
- Created Secret is selected after returning.

### Step 2: Add explicit selection policy

```typescript
function selectInitialSecret(options: SecretListItem[]): string {
  if (options.length === 1) return options[0].name
  const defaults = options.filter((option) => option.is_default)
  return defaults.length === 1 ? defaults[0].name : ''
}
```

Run this only when no user selection exists. Track whether the user explicitly cleared the field so background refetches do not reselect it.

### Step 3: Add the Agent Dialog subview

```typescript
type AgentDialogView = 'agent_form' | 'create_llm_secret'
```

Keep Agent form state in the parent component. The subview renders `LlmSecretConfigurator` with fixed Engine and no nested `Dialog`.

### Step 4: Implement edit conflict handling

- Query compatible options for the proposed Engine.
- If the persisted Secret is not in those options, fetch exact metadata for display.
- Keep the value visible.
- Show “重新选择模型配置 / 恢复原引擎”.
- Disable save until resolved.
- Never turn the conflict into an empty field without explanation.

### Step 5: Replace the old picker

Migrate create/edit callers to `CompatibleSecretPicker`, then remove `model-secret-select.tsx`.

### Step 6: Write failing Quickstart tests

Assert:

- Quickstart uses the same compatible Secret hook and initial selection policy.
- API request sends `engine_kind`, not `provider`.
- No compatible Secret opens inline configuration in the same wizard step.
- Quickstart draft state survives entering and leaving configuration.

### Step 7: Define and use `returnToEngineStep`

In Quickstart, define the callback before rendering the configurator:

```typescript
const returnToEngineStep = useCallback(() => {
  setInlineSecretMode(false)
  setCurrentStep(1)
}, [])
```

The callback exits inline Secret configuration, returns to the Engine/model-selection step, and preserves all wizard draft state stored above the step view.

When creation succeeds:

```typescript
onCreated={(secret) => {
  setSecretRef(secret.name)
  setInlineSecretMode(false)
  setCurrentStep(2)
}}
```

Adjust exact step numbers to the existing wizard constants, but keep the named callback and behavior explicit.

### Step 8: Run tests

```bash
cd frontend
bun run test -- \
  app/managed/agents/components/agent-secret-selection.test.tsx \
  app/managed/agents/components/create-agent-dialog.test.tsx \
  'app/managed/agents/[agentId]/edit/page.test.tsx' \
  lib/managed/quickstart-create.test.ts
bun run type-check
```

---

## Task 10: Documentation and End-to-End Verification

**Files:**
- Modify `docs/api/openapi.md`
- Modify `docs/tutorials/01-model-provider-setup.md`
- Modify `docs/tutorials/04-agent-build-and-run.md`

### Step 1: Update documentation

Document:

- Provider is a model service supplier, not an Agent Engine.
- Engine capabilities are development-time contracts.
- Secret creation Engine selection is only a filter.
- LLM Secret requires explicit Provider and Protocol.
- Generic Secret has no Provider or Protocol.
- Agent and Quickstart use server-filtered compatible Secrets.
- Defaults are Protocol-scoped.
- Catalog endpoint and Secret query parameters.
- Quickstart request uses `engine_kind`.

### Step 2: Run focused backend verification

```bash
cd backend
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_llm_catalog.py \
  tests/test_llm_catalog_api.py \
  tests/test_llm_secret_schema.py \
  tests/test_llm_secret_catalog.py \
  tests/test_llm_agent_compatibility.py \
  tests/test_llm_quickstart_compatibility.py \
  tests/test_llm_runtime_catalog_contract.py \
  tests/test_secret_connectivity.py -v
UV_CACHE_DIR=/tmp/joysafeter-uv-cache uv run alembic heads
```

Require only `20260803_000001 (head)`.

### Step 3: Run focused frontend verification

```bash
cd frontend
bun run test -- \
  lib/managed/llm-catalog.test.ts \
  hooks/managed/use-compatible-secrets.test.tsx \
  components/managed/llm/llm-secret-configurator.test.tsx \
  components/managed/llm/compatible-secret-picker.test.tsx \
  app/managed/secrets/components/create-secret-dialog.test.tsx \
  app/managed/agents/components/agent-secret-selection.test.tsx \
  app/managed/agents/components/create-agent-dialog.test.tsx \
  'app/managed/agents/[agentId]/edit/page.test.tsx' \
  lib/managed/quickstart-create.test.ts
bun run type-check
```

### Step 4: Run Rust verification

```bash
cd backend/app/joysafeter_orchestrator_rs
cargo test llm_catalog
cargo test llm_providers
cargo test harness_input_builder
cargo test sandbox_resolver
```

### Step 5: Run repository checks

```bash
git diff --check
rg -n 'provider\s*[:=].*(claude|codex|native|pi)|_secret_matches_engine|_provider_family|apply_provider_aliases' \
  backend frontend
```

Expected: no LLM Secret write path, compatibility helper, or Quickstart request still treats Engine IDs as Provider IDs. Engine declarations and display strings may still contain these names.

### Step 6: Manual acceptance

Verify in browser:

1. Secret page creates Anthropic, OpenAI, DeepSeek, Custom, and Generic configurations.
2. Claude only sees Anthropic Messages configurations.
3. Codex only sees OpenAI Responses configurations.
4. Native/Pi see all declared Protocols.
5. Engine changes do not silently replace a selected Secret.
6. Agent edit shows and blocks an incompatible persisted selection.
7. Agent and Quickstart create a model configuration inline without losing drafts.
8. Loading, failure, retry, keyboard, focus, and small-screen states are usable.

## Completion Criteria

- Catalog is the only Engine/Protocol/Provider capability source.
- Initial schema directly enforces explicit Secret identity.
- Alembic has one head: `20260803_000001`.
- Secret filtering occurs before pagination.
- Agent create/update and Quickstart reject invalid combinations.
- Rust rejects invalid metadata before decryption.
- Frontend linked selectors and inline creation use shared components.
- No path infers identity from keys, URL, or Engine-named Provider values.
- Targeted Python, frontend, Rust, schema, and manual checks pass.

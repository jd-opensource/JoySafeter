# Credential Material Access Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure runtime reference validation does not decrypt credential values, every actual material reveal is field-scoped, and Python/Rust consumers emit one non-secret, attributable access-audit contract.

**Architecture:** Keep binding and usage policy in the Credential domain/application boundary. Split Rust metadata validation from material reveal, then add a dedicated append-only access-audit record whose unique runtime key provides success-event idempotency. Python request consumers record the authenticated principal; Rust runtime consumers record session/task/generation identity. Audit failure behavior is explicit per boundary rather than hidden inside the cipher adapter.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Rust, Tokio, SQLx, PostgreSQL, pytest, cargo test.

**Spec:** `docs/superpowers/evidence/2026-08-22-credential-lifecycle-deep-audit.md`

**Progress on 2026-08-22:** The field-selective reveal primitive, material-free metadata record, metadata lock path, metadata policy validators, snapshot call-site migration, model catalog field selection, HTTP egress single-field load, and MCP `token_value`-only reveal are implemented. The append-only access-audit table, migration, and Python access-event service are implemented; Rust runtime emitters remain pending. Full environment injection intentionally authorizes all fields.

## Global Constraints

- Never persist plaintext values, hashes of plaintext values, authorization headers, cookies, or raw credential payloads in audit records.
- Keep credential reference production writes on v1; retain legacy-v0/v1/v2 reads.
- Keep `enc:v1` ciphertext compatibility and `JOYSAFETER_VAULT_ENCRYPTION_KEY` support.
- Snapshot validation may inspect metadata and encrypted field names, but must not decrypt values.
- Material access must fail closed on project, lifecycle, kind, identity, field, or envelope errors.
- Successful runtime events are idempotent per `(session_id, generation, credential_id, usage, consumer_type, consumer_id)`.
- Do not commit changes automatically; the current worktree contains unrelated user modifications.

---

### Task 1: Define Access Audit Persistence Contract

**Files:**
- Create: `backend/app/joysafeter_domain/models/joysafeter_credential_access_audit.py`
- Modify: `backend/app/joysafeter_domain/models/__init__.py`
- Create: `backend/alembic/versions/<revision>_add_credential_access_audit.py`
- Create: `backend/tests/test_credential_access_audit_model.py`

**Interfaces:**
- Produces an append-only row keyed by a generated UUID.
- Accepts only identifiers, usage metadata, field names, result, and stable error code.
- Provides a partial unique index for successful runtime access deduplication.
- Keeps the immutable typed credential ID without a foreign key. This avoids a
  dedicated audit transaction blocking on a credential row locked by the
  business transaction, and lets evidence survive physical credential removal.

- [x] **Step 1: Write failing model and migration contract tests**

```python
def test_access_audit_has_no_material_columns() -> None:
    names = set(JoySafeterCredentialAccessAudit.__table__.columns.keys())
    assert {"value", "data", "payload", "ciphertext", "secret"}.isdisjoint(names)


def test_runtime_success_dedupe_key_is_declared() -> None:
    assert expected_runtime_dedupe_index(JoySafeterCredentialAccessAudit.__table__)
```

- [x] **Step 2: Run the focused tests and confirm they fail**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_access_audit_model.py`

- [x] **Step 3: Add the model and migration**

Use explicit columns:

```python
project_id: Mapped[str]
credential_id: Mapped[CredentialId | None]
credential_kind: Mapped[str | None]
usage: Mapped[str]
consumer_type: Mapped[str]
consumer_id: Mapped[str | None]
principal_type: Mapped[str | None]
principal_id: Mapped[str | None]
session_id: Mapped[SessionId | None]
task_id: Mapped[TaskId | None]
generation: Mapped[int | None]
field_names: Mapped[list[str]]
result: Mapped[str]
error_code: Mapped[str | None]
```

Do not add a credential foreign key: a dedicated audit transaction must not
wait on a credential row held `FOR UPDATE` by the business transaction. The
typed `credential_id` is immutable evidence and survives credential purge.

- [x] **Step 4: Verify migration upgrade and downgrade against PostgreSQL**

Run the repository migration checks documented in `DEVELOPMENT.md`, then rerun the focused model test.

---

### Task 2: Split Rust Metadata Validation From Reveal — Complete

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/record.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/material.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/store.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/credential_store_integration.rs`

**Interfaces:**
- Produces `CredentialMetadataRecord`, which contains identity/state metadata and encrypted field names but no plaintext material.
- Produces `CredentialStore::lock_active_metadata(...)` for snapshot validation.
- Produces `CredentialStore::load_active_fields(..., requested_fields)` for actual use.

- [x] **Step 1: Add failing tests proving metadata reads never invoke the protector**

Use a test protector that counts reveal calls and assert:

```rust
let metadata = store.lock_active_metadata(&mut connection, &project_id, credential_id).await?;
assert_eq!(metadata.id, credential_id);
assert_eq!(protector.reveal_count(), 0);
```

- [x] **Step 2: Add failing tests proving unauthorized fields are never decrypted**

Store two encrypted fields, make the unused field intentionally invalid, request only the authorized field, and require success. Then request the invalid field and require `EnvelopeInvalid`.

- [x] **Step 3: Introduce metadata and field-selection types**

```rust
pub struct CredentialMetadataRecord {
    pub id: CredentialId,
    pub project_id: ProjectId,
    pub kind: CredentialKind,
    pub provider: Option<String>,
    pub protocol: Option<String>,
    pub group_id: Option<CredentialGroupId>,
    pub server_url: Option<String>,
    pub normalized_server_url: Option<String>,
    pub auth_scheme: Option<String>,
    pub material_fields: BTreeSet<String>,
}

pub enum MaterialFieldSelection<'a> {
    All,
    Only(&'a BTreeSet<String>),
}
```

- [x] **Step 4: Implement field-scoped reveal**

```rust
pub fn reveal_fields(
    &self,
    stored: &Value,
    selection: MaterialFieldSelection<'_>,
) -> Result<CredentialMaterial, CredentialRuntimeError>
```

Validate the JSON object first, select encrypted fields second, decrypt selected values third, and report missing requested fields without decrypting unrelated entries.

- [x] **Step 5: Split store methods without weakening state validation**

Factor project/lifecycle/kind/identity checks into one metadata constructor. `lock_active_metadata` must omit `data` from its SQL projection where practical. `load_active_fields` may fetch `data` but must call `reveal_fields` with the usage-authorized selection.

- [x] **Step 6: Run Rust unit and store integration tests**

Run: `cargo test -p joysafeter-orchestrator credential_store`

---

### Task 3: Make Snapshot Validation Metadata-Only — Complete

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/snapshot.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/model.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/service.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/credential_snapshot_linearization.rs`

**Interfaces:**
- Consumes `CredentialMetadataRecord` and encrypted field-name descriptors.
- Produces the same v1 snapshot document as before.
- Defers ciphertext authentication/decryption until material is actually consumed.

- [x] **Step 1: Add a failing snapshot test with valid metadata and invalid unused ciphertext**

The snapshot must succeed when required field names exist, proving it does not decrypt. Runtime material resolution must still fail closed if the selected ciphertext is invalid.

- [x] **Step 2: Add metadata-only policy validators**

```rust
pub fn validate_model_credential_metadata(
    record: &CredentialMetadataRecord,
    engine_kind: &str,
) -> Result<(), CredentialRuntimeError>;

pub fn validate_service_credential_metadata(
    record: &CredentialMetadataRecord,
    usage: ServiceUsage<'_>,
) -> Result<(), CredentialRuntimeError>;
```

- [x] **Step 3: Replace snapshot `lock_active` calls**

Use `lock_active_metadata` and metadata-only validators. Preserve deterministic lock ordering, project checks, lifecycle checks, kind checks, required-field-name checks, and v1 encoding.

- [x] **Step 4: Run snapshot linearization and reference compatibility tests**

Run: `cargo test -p joysafeter-orchestrator credential_snapshot`

---

### Task 4: Route Runtime Consumers Through Field-Scoped Loads — Complete

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/model.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/service.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mcp.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/store.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/credential_runtime_contract.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/credential_store_integration.rs`

**Interfaces:**
- Model usage requests catalog-required fields and accepted alternatives.
- HTTP egress requests exactly the configured injection field.
- MCP requests exactly the canonical token field for its auth scheme.
- Environment injection requests all fields only because that binding explicitly authorizes all fields.

- [x] **Step 1: Add consumer-specific negative tests**

For each usage, include an invalid unrequested ciphertext field and assert successful resolution. Include a missing requested field and assert `FieldMissing`.

- [x] **Step 2: Change resolvers to derive field selections before reveal**

Resolvers must not receive a material-bearing record until metadata policy has passed. The store receives the approved field selection rather than letting callers index a fully revealed map.

- [x] **Step 3: Preserve redacted debug behavior**

Tests must prove `Debug` output contains field names at most and never plaintext values.

- [x] **Step 4: Run focused Rust runtime tests**

Run: `cargo test -p joysafeter-orchestrator credential_runtime_contract credential_store_integration`

---

### Task 5: Add Python Request-Scoped Access Auditing

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/ports.py`
- Modify: `backend/app/joysafeter_application/credentials/composition.py`
- Create: `backend/app/joysafeter_infrastructure/credentials/access_audit_adapter.py`
- Modify: `backend/app/joysafeter_api/api/v1/quickstart.py`
- Modify: `backend/app/joysafeter_api/api/v1/skills_ai_authoring.py`
- Move: `backend/app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py` → `backend/app/joysafeter_application/credentials/webhook_auth_service.py`
- Create: `backend/tests/test_credential_material_access_audit.py`

**Interfaces:**
- Adds an immutable `CredentialAccessContext` passed by the caller, not inferred by the material adapter.
- Uses the exact `JoySafeterAuthContext.principal_type` and `principal_id` for request consumers.
- Emits only after policy validation identifies authorized field names.

- [x] **Step 1: Write failing tests for success, denial, and no-secret payloads**

```python
assert entry.field_names == ["OPENAI_API_KEY"]
assert entry.principal_type == "api_key"
assert entry.principal_id == str(api_key_id)
assert secret_value not in serialized_entry
```

- [x] **Step 2: Define caller-owned access context**

```python
@dataclass(frozen=True, slots=True)
class CredentialAccessContext:
    consumer_type: str
    actor: CredentialAuditActor
    consumer_id: str | None = None
    session_id: SessionId | None = None
    task_id: TaskId | None = None
    generation: int | None = None
```

- [x] **Step 3: Keep reveal and audit orchestration above the cipher adapter**

Add an Application service method that validates the binding, invokes `material_adapter.load`, and appends success/failure audit with authorized field names. Do not add request/session concerns to `ManagedCredentialMaterialAdapter`.

- [x] **Step 4: Migrate Python consumers**

Quickstart and skill authoring pass request principals. Webhook auth passes trigger identity and system/request attribution after its orchestration is moved out of Domain.

- [x] **Step 5: Run focused Python tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_material_access_audit.py backend/tests/test_credential_ephemeral_consumers.py backend/tests/test_trigger_webhook_auth_credential.py`

---

### Task 6: Add Rust Runtime Access Auditing — Complete

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/audit.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mod.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/store.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/credential_store_integration.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/credential_runtime_contract.rs`

**Interfaces:**
- `CredentialAccessAuditWriter::append_success` uses `ON CONFLICT DO NOTHING` for the runtime dedupe key.
- `append_failure` records each denied/failed attempt and stable error code.
- No audit method accepts plaintext material.

- [x] **Step 1: Write failing idempotency and redaction tests**

Resolve the same credential twice for the same session generation and assert one success row. Resolve it for a new generation and assert a second row. Assert serialized audit data excludes plaintext.

- [x] **Step 2: Implement the SQLx audit writer**

The writer receives identifiers and field names only. Use the same transaction when access is part of a transactional scheduling operation; otherwise use a bounded dedicated write and make the chosen failure policy explicit.

- [x] **Step 3: Emit after successful reveal and on denied access**

Do not emit a success event at snapshot validation. Emit when model, environment, HTTP egress, or MCP material is actually resolved.

- [x] **Step 4: Run Rust integration tests against PostgreSQL**

Run: `cargo test -p joysafeter-orchestrator credential_store_integration credential_runtime_contract`

---

### Task 7: Propagate Mutation Actor Identity

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/ports.py`
- Modify: `backend/app/joysafeter_application/credentials/composition.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/audit_adapter.py`
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Modify: `backend/app/joysafeter_api/api/v1/credential_groups.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/app/joysafeter_api/api/v1/tasks.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_service.py`
- Modify: credential mutation tests under `backend/tests/`

**Interfaces:**
- Composition accepts an immutable actor descriptor constructed from `JoySafeterAuthContext` and request metadata.
- Audit rows retain the human `user_id` when available and add `principal_type`/`principal_id` to details.
- System-initiated changes use an explicit `principal_type="system"`; they do not silently appear anonymous.

- [x] **Step 1: Add failing actor-attribution tests for human and API-key principals**
- [x] **Step 2: Add the immutable actor descriptor**
- [x] **Step 3: Pass actor data from API routes into composition**
- [x] **Step 4: Remove hard-coded `ip_address="application"` where request metadata is available**
- [x] **Step 5: Run credential mutation and auth audit suites**

The completed propagation also covers the two other writers sharing the same
Credential audit port: Environment credential-binding changes and Session
snapshot creation. Environment creation now records initial bindings while
keeping runtime refresh impacts update-only.

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_service.py backend/tests/test_credential_group_service.py backend/tests/test_api_key_lifecycle_audit.py`

---

### Task 8: Add Architecture Guards and Final Verification

**Files:**
- Modify: `backend/tests/test_credential_application_boundaries.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/superpowers/evidence/2026-08-22-credential-lifecycle-deep-audit.md`

**Interfaces:**
- No new `joysafeter_domain` import may point to `joysafeter_application` or `joysafeter_infrastructure`.
- Existing reverse imports must be enumerated as temporary debt until moved in a separate ownership migration.

- [x] **Step 1: Add an exact reverse-import inventory test**
- [x] **Step 2: Update architecture documentation with the material-access flow**
- [x] **Step 3: Run Ruff, Python tests, Rust fmt/check/tests, and `git diff --check`**

Minimum verification:

```bash
backend/.venv/bin/ruff check backend/app backend/tests
backend/.venv/bin/pytest -q backend/tests/test_credential_application_boundaries.py backend/tests/test_credential_service.py backend/tests/test_credential_group_service.py backend/tests/test_credential_ephemeral_consumers.py
(cd backend/app/joysafeter_orchestrator_rs && cargo fmt --check && cargo test)
git diff --check
```

## Explicitly Out of Scope

- Credential/API-key purge and retention implementation.
- API-key expiry API/UI rollout.
- API-key prefix migration.
- `enc:v2` or credential reference v2 production writes.
- Renaming `JOYSAFETER_VAULT_ENCRYPTION_KEY` without a dual-read deployment migration.
- Moving the two remaining legacy Domain orchestration services; that requires separate ownership plans after this material-access boundary is stable. `SessionResourceService`, credential-aware Session creation, Environment credential transaction coordination, and Trigger execution/fire orchestration have already moved to Application as isolated ownership corrections.

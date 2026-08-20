# P0.5 Credential Domain Closure Implementation Plan

> **Superseded execution tail (2026-08-19):** Tasks 13–15 are not active. Their v2 writer/backfill scope is replaced by `docs/superpowers/plans/2026-08-19-credential-domain-closure-v1-freeze.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Managed Credential domain across Python, Rust, Frontend, persistence references, lifecycle transactions, Snapshot materialization, and runtime resolution without introducing production `enc:v2` behavior.

**Architecture:** Establish shared machine-readable contracts, a framework-free Credential Domain Core, Application-owned transactions and ports, separate Material Adapters for Managed Credential/Task Identity/Repository Access, and one Rust Credential Store. Roll out reference versioning as reader-first E1, writer cutover E2, and resumable live-data contract E3; immutable historical Snapshots remain readable through scoped legacy decoders.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL JSONB/advisory locks, Rust/sqlx/Tokio, Next.js/TypeScript/Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-16-credential-domain-closure-p0-5-design.md`

## Global Constraints

- Database rollback floor is Alembic revision `20260815_000002`; “reversible” never means returning to the pre-P0 schema.
- Keep `enc:v1`; do not add production AAD, HKDF, Keyring, `key_id`, or `enc:v2` writes.
- Persist only Credential kinds `model`, `service`, and `mcp`; Rust must not require or persist `llm` as a Credential kind.
- Treat legacy MCP `bearer` as read-compatible `static_bearer`; unknown schemes fail closed.
- Require non-null project scope for every Managed Credential runtime lookup.
- Only an absent optional Binding may return `NotBound`; a persisted invalid ID must fail closed.
- Snapshots remain immutable and contain references only; MCP Group members remain live-resolved.
- Agent Version Snapshot references are revalidated on activation; only active Session Snapshots block lifecycle changes.
- Managed Credential, Task Identity, and Repository Access use separate Material Adapters.
- Browser instances are not part of the observable persistence-writer fleet; Backend canonicalizes stale old/new API input under the server write-version flag.
- Mutation, Audit, durable impact pending, and lifecycle state change commit in one transaction; network nudge is best-effort after commit.
- Historical `secret_ref`, `secret_refs`, `service_credential_id`, and `secret_key` remain permitted only inside legacy-v0/v1 decoders and compatibility fixtures.
- Do not commit or push during execution unless the user explicitly requests it.

---

### Task 1: Build P0.5 Preflight Inventory

**Files:**
- Create: `backend/scripts/credential_p0_5_preflight.py`
- Create: `backend/tests/test_credential_p0_5_preflight.py`
- Create: `backend/contracts/credential_p0_5_preflight.schema.json`

**Interfaces:**
- Produces a deterministic JSON report consumed by Tasks 8, 13, 14, and 15.
- Does not mutate data.

```python
@dataclass(frozen=True)
class CredentialPreflightReport:
    invalid_resources: tuple[dict[str, str], ...]
    credential_type_counts: Mapping[str, int]
    snapshot_schema_counts: Mapping[str, int]
    legacy_reference_counts: Mapping[str, int]
    cross_project_references: tuple[dict[str, str], ...]
    null_project_references: tuple[dict[str, str], ...]
    mcp_url_conflicts: tuple[dict[str, str], ...]
```

- [ ] **Step 1: Write failing report-shape tests**

```python
async def test_preflight_reports_unknown_snapshot_and_null_project_reference(db_session):
    await seed_session_with_unknown_snapshot_and_credential_ref(db_session)
    report = await collect_credential_preflight(db_session)
    assert report.snapshot_schema_counts["unknown"] == 1
    assert report.null_project_references[0]["surface"] == "session_snapshot"
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_p0_5_preflight.py`

Expected: FAIL because `collect_credential_preflight` and the JSON schema do not exist.

- [ ] **Step 3: Implement read-only inventory queries**

The command must report resource IDs and field paths for invalid kind combinations, distinct `credential_type`, Agent Version/Session Snapshot schema `legacy-v0/v1/v2/unknown`, all legacy reference paths including top-level `service_credential_id`, project mismatches, project-null references, and MCP normalized-URL conflicts.

- [ ] **Step 4: Add CLI serialization and schema validation**

Run shape: `backend/.venv/bin/python backend/scripts/credential_p0_5_preflight.py --output /tmp/credential-p0-5-preflight.json`

Exit `0` only when the report is structurally valid; use `--fail-on-blocker` to return non-zero for invalid rows, unknown schemas, cross-project references, or URL conflicts.

- [ ] **Step 5: Verify tests and a disposable-database run**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_p0_5_preflight.py`

Run: `backend/.venv/bin/python backend/scripts/credential_p0_5_preflight.py --fail-on-blocker --output /tmp/credential-p0-5-preflight.json`

Expected: tests PASS; command emits no plaintext, ciphertext, config payload, or masked suffix.

---

### Task 2: Freeze Cross-Language Credential Contracts

**Files:**
- Create: `backend/contracts/credential_domain_contract.json`
- Create: `backend/contracts/credential_reference_contract.json`
- Create: `backend/tests/test_credential_domain_contract.py`
- Modify: `backend/tests/test_credential_cipher_contract.py`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mod.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/contract.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/error.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mod.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/llm_catalog.rs`

**Interfaces:**
- Defines Credential kind, auth-scheme aliases, runtime error classes, Snapshot schemas, canonical reference keys, and legacy aliases.

```json
{
  "credential_kinds": ["model", "service", "mcp"],
  "auth_scheme_aliases": {"bearer": "static_bearer"},
  "runtime_errors": [
    "not_bound", "not_found", "archived", "project_mismatch",
    "kind_mismatch", "field_missing", "unsupported_scheme",
    "corrupt_record", "envelope_invalid"
  ]
}
```

- [ ] **Step 1: Write failing Python contract tests**

```python
def test_model_is_only_model_credential_kind(contract):
    assert contract["credential_kinds"] == ["model", "service", "mcp"]
    assert "llm" not in contract["credential_kinds"]

def test_only_reviewed_legacy_auth_alias_exists(contract):
    assert contract["auth_scheme_aliases"] == {"bearer": "static_bearer"}
```

- [ ] **Step 2: Write failing Rust contract tests**

```rust
#[test]
fn db_model_kind_is_valid() {
    assert!(CredentialContract::embedded().is_kind("model"));
    assert!(!CredentialContract::embedded().is_kind("llm"));
}
```

- [ ] **Step 3: Run tests and verify current mismatch**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_domain_contract.py backend/tests/test_credential_cipher_contract.py`

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml credentials::contract llm_catalog -- --nocapture`

Expected: FAIL on the current Rust `llm` expectation and missing contract artifacts.

- [ ] **Step 4: Implement contract loaders and canonical auth mapping**

```rust
pub fn canonical_auth_scheme(raw: &str) -> Result<&'static str, CredentialRuntimeError> {
    match raw {
        "static_bearer" | "bearer" => Ok("static_bearer"),
        "oauth" | "mcp_oauth" => Err(CredentialRuntimeError::UnsupportedScheme),
        _ => Err(CredentialRuntimeError::CorruptRecord),
    }
}
```

- [ ] **Step 5: Replace `llm` Credential-kind validation with `model`**

Update `llm_catalog.rs` tests to use real DB value `model`; retain LLM terminology only for Catalog/product concepts.

- [ ] **Step 6: Re-run focused Python and Rust suites**

Expected: PASS with both implementations reading the same artifacts.

---

### Task 3: Close Current Runtime Fail-Open Paths

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/error.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/run_spec.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/tests/credential_runtime_contract.rs`

**Interfaces:**
- Makes P0.5-0 safe before the later Store extraction.

```rust
fn require_bound_project<'a>(
    project_id: Option<&'a str>,
    credential_id: CredentialId,
) -> Result<&'a str, CredentialRuntimeError>;
```

- [ ] **Step 1: Add real-PostgreSQL failing tests**

Test these cases: absent optional Binding → `NotBound`; configured missing ID → `NotFound`; archived row → `Archived`; wrong project → `ProjectMismatch`; null project with configured ID → `ProjectMismatch`; malformed material → `CorruptRecord`; missing required field → `FieldMissing`.

- [ ] **Step 2: Run the runtime integration test**

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --test credential_runtime_contract -- --nocapture`

Expected: FAIL because current code returns `Ok(None)` or relaxes project filtering.

- [ ] **Step 3: Remove nullable-project SQL relaxation**

Replace `($2::text IS NULL OR project_id = $2)` for bound Credential lookups with mandatory project equality after `require_bound_project`.

- [ ] **Step 4: Separate NotBound from invalid bound references**

Only the absence of the persisted reference key/column returns `NotBound`; a present ID never returns `None` on lookup failure.

- [ ] **Step 5: Make HTTP Egress and MCP required material fail closed**

Configured Egress/MCP bindings must return typed errors for missing rows, missing fields, unsupported schemes, or malformed envelopes instead of skipping injection.

- [ ] **Step 6: Re-run the integration test and existing Rust tests**

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml`

Expected: PASS; P0.5-0 runtime contract is independently deployable.

---

### Task 4: Introduce the Framework-Free Domain Core

**Files:**
- Create: `backend/app/joysafeter_domain/credentials/__init__.py`
- Create: `backend/app/joysafeter_domain/credentials/types.py`
- Create: `backend/app/joysafeter_domain/credentials/resource.py`
- Create: `backend/app/joysafeter_domain/credentials/material.py`
- Create: `backend/app/joysafeter_domain/credentials/bindings.py`
- Create: `backend/app/joysafeter_domain/credentials/policies.py`
- Create: `backend/app/joysafeter_domain/credentials/lifecycle.py`
- Create: `backend/app/joysafeter_domain/credentials/references.py`
- Create: `backend/app/joysafeter_domain/credentials/dependencies.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_credential.py`
- Create: `backend/tests/test_credential_domain_core.py`
- Create: `backend/tests/test_credential_domain_architecture.py`

**Interfaces:**

```python
ProjectId = NewType("ProjectId", str)
```

`ProjectId` is constructed only from a trimmed non-empty project identifier. Managed Credential policies and runtime ports do not accept `str | None` for project scope.

```python
CredentialBinding = (
    ModelInferenceBinding
    | WebhookAuthBinding
    | EnvironmentInjectionBinding
    | HttpEgressBinding
    | McpGroupBinding
)
```

```python
@dataclass(frozen=True)
class CredentialResource:
    id: CredentialId
    project_id: ProjectId
    name: str
    kind: CredentialKind
    identity: CredentialIdentity
    material: CredentialMaterialDescriptor
    state: CredentialState
    is_default: bool
```

- [ ] **Step 1: Write failing value-object and policy tests**

```python
def test_sensitive_value_never_reveals_in_repr_or_str():
    value = SensitiveValue("sk-never-print")
    assert "sk-never-print" not in repr(value)
    assert "sk-never-print" not in str(value)

def test_material_copies_input_mapping():
    raw = {CredentialFieldName("API_KEY"): SensitiveValue("x")}
    material = CredentialMaterial(raw)
    raw.clear()
    assert material.field_names == frozenset({CredentialFieldName("API_KEY")})
```

- [ ] **Step 2: Write failing discriminated Binding tests**

Cover Catalog context, webhook method/field, Environment POSIX names, HTTP endpoint/inject, MCP Group URLs, archived/deleted rejection, and `OAUTH2_LEGACY_DISABLED`.

- [ ] **Step 3: Write the import-graph guard**

Fail if Domain Core imports Pydantic, SQLAlchemy, FastAPI, Redis, API routers, HTTP clients, Application, or Infrastructure.

- [ ] **Step 4: Run focused tests and verify package absence**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_domain_core.py backend/tests/test_credential_domain_architecture.py`

- [ ] **Step 5: Implement exact limits and immutable types**

Define `ProjectId` in `types.py`. Use maximum 50 fields, 128 Unicode characters per field name, 8192 Unicode characters per value, flat strings only, and stricter POSIX syntax for Environment Injection.

- [ ] **Step 6: Make Pydantic schemas import Domain enums/types**

Transport schemas keep trimming/parsing only; kind/usage/state decisions move to Domain policies.

- [ ] **Step 7: Re-run focused tests**

Expected: PASS with no framework imports in Domain Core.

---

### Task 5: Establish Application Ports and Separate Material Adapters

**Files:**
- Create: `backend/app/joysafeter_application/__init__.py`
- Create: `backend/app/joysafeter_application/credentials/__init__.py`
- Create: `backend/app/joysafeter_application/credentials/ports.py`
- Create: `backend/app/joysafeter_application/credentials/resource_service.py`
- Create: `backend/app/joysafeter_application/credentials/group_service.py`
- Create: `backend/app/joysafeter_application/credentials/binding_service.py`
- Create: `backend/app/joysafeter_application/credentials/snapshot_service.py`
- Create: `backend/app/joysafeter_application/credentials/composition.py`
- Create: `backend/app/joysafeter_infrastructure/__init__.py`
- Create: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Create: `backend/app/joysafeter_infrastructure/credentials/material_adapter.py`
- Create: `backend/app/joysafeter_infrastructure/credentials/network_policy_adapter.py`
- Create: `backend/app/joysafeter_infrastructure/credentials/audit_adapter.py`
- Create: `backend/app/joysafeter_infrastructure/task_identity/material_adapter.py`
- Create: `backend/app/joysafeter_infrastructure/repository_access/material_adapter.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_resource_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/agent_identity_capture.py`
- Create: `backend/tests/test_credential_application_boundaries.py`

**Interfaces:**

```python
class CredentialMaterialPort(Protocol):
    async def load(
        self,
        binding: ValidatedCredentialBinding,
    ) -> ResolvedCredentialMaterial: ...
```

`ResolvedCredentialMaterial` contains only fields authorized by the validated Binding; Environment Injection is the only Binding allowed to request all fields.

```python
class CredentialUnitOfWork(Protocol):
    credentials: CredentialRepositoryPort
    groups: CredentialGroupRepositoryPort
    audit: CredentialAuditPort
    impacts: CredentialImpactPort
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

- [ ] **Step 1: Add failing boundary tests**

Assert old Credential Service no longer imports API refresh/Pydantic requests, Repository code no longer calls Credential Service encryption helpers, and Task Identity no longer instantiates `CredentialCipher` directly.

- [ ] **Step 2: Run focused boundary tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_application_boundaries.py backend/tests/test_foundation3_task_identity.py backend/tests/test_session_resource_error_contract.py`

- [ ] **Step 3: Define repository, material, audit, impact, transaction, and scanner ports**

Ports live in Application; pure Domain metadata does not import them.

- [ ] **Step 4: Implement three separate legacy-v1 adapters**

Managed Credential, Task Identity, and Repository Access may share a low-level `LegacyV1MaterialProtector`, but expose distinct purpose-specific methods and never call one another’s Application Service.

- [ ] **Step 5: Convert the old Credential Service into a compatibility facade**

The facade delegates to Application services while preserving existing public errors until consumers migrate.

- [ ] **Step 6: Re-run boundary and existing service tests**

Expected: PASS without changing ciphertext format.

---

### Task 6: Migrate Persistent Consumers to Binding Policy

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_service.py`
- Modify: `backend/tests/test_agent_model_credential_ref.py`
- Modify: `backend/tests/test_trigger_webhook_auth_credential.py`
- Modify: `backend/tests/test_environment_credential_refs.py`
- Modify: `backend/tests/test_session_credential_groups.py`

**Interfaces:**
- Agent uses `ModelInferenceBinding`.
- Trigger uses `WebhookAuthBinding`.
- Environment uses `EnvironmentInjectionBinding` and `HttpEgressBinding`.
- Session Group authorization uses `McpGroupBinding`.

- [ ] **Step 1: Add failing archived/deleted/cross-project policy tests**

```python
async def test_environment_http_egress_rejects_archived_credential(...):
    with pytest.raises(ResourceConflictError) as exc:
        await update_environment_with_egress(...)
    assert exc.value.code == "CREDENTIAL_STATE_INVALID"
```

- [ ] **Step 2: Add failing Usage-specific tests**

Cover model engine/protocol compatibility, webhook auth method and field, HTTP endpoint/inject field, Environment POSIX names, and MCP URL conflicts.

- [ ] **Step 3: Run focused consumer tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_agent_model_credential_ref.py backend/tests/test_trigger_webhook_auth_credential.py backend/tests/test_environment_credential_refs.py backend/tests/test_session_credential_groups.py`

- [ ] **Step 4: Replace direct kind/state/field checks with Binding Service calls**

No consumer may compare `cred.kind` or decrypt material directly after migration.

- [ ] **Step 5: Route Environment mutation through Application transaction hooks**

Environment config mutation and durable policy-pending impact must be prepared in the same transaction; no post-commit second mutation transaction remains.

- [ ] **Step 6: Re-run focused tests**

Expected: PASS with unchanged public success payloads and canonical Credential error codes.

---

### Task 7: Migrate Ephemeral Model Consumers

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/quickstart.py`
- Modify: `backend/app/joysafeter_api/api/v1/skills_ai_authoring.py`
- Create: `backend/tests/test_credential_ephemeral_consumers.py`
- Modify: `backend/tests/test_quickstart_error_contract.py`
- Modify: `backend/tests/test_skill_authoring_error_contract.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class NoPersistentDependencyScanner:
    reason: Literal["ephemeral_consumer"] = "ephemeral_consumer"
```

- [ ] **Step 1: Add failing tests for archived, missing, wrong-project, and incompatible model Credentials**

Both endpoints must call the same `ModelInferenceBinding` policy used by Agent runtime configuration.

- [ ] **Step 2: Add a test proving no persistent dependency is created**

The descriptor must explicitly carry `NoPersistentDependencyScanner`, not omit scanner metadata.

- [ ] **Step 3: Run focused endpoint tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_ephemeral_consumers.py backend/tests/test_quickstart_error_contract.py backend/tests/test_skill_authoring_error_contract.py`

- [ ] **Step 4: Replace direct Credential Service get/decrypt calls**

Load only Catalog-authorized model fields through `CredentialMaterialPort.load(validated_binding)`.

- [ ] **Step 5: Re-run focused tests**

Expected: PASS; archived Credentials can no longer be used by ephemeral consumers.

---

### Task 8: Build Reference Registry, Dispositions, and Production Shadow

**Files:**
- Create: `backend/app/joysafeter_infrastructure/credentials/dependency_scanners.py`
- Modify: `backend/app/joysafeter_application/credentials/composition.py`
- Modify: `backend/app/joysafeter_domain/credentials/dependencies.py`
- Create: `backend/contracts/credential_reference_surface_exceptions.json`
- Create: `backend/tests/test_credential_reference_registry.py`
- Create: `backend/tests/test_credential_reference_reverse_census.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_service.py`
- Modify: `backend/app/joysafeter_shared/config/settings.py`
- Modify: `deploy/docker-compose.yml`

**Interfaces:**

```python
class DependencyDisposition(StrEnum):
    BLOCK_RESOURCE_ARCHIVE = "block_resource_archive"
    BLOCK_RESOURCE_DELETE = "block_resource_delete"
    BLOCK_GROUP_ARCHIVE = "block_group_archive"
    BLOCK_GROUP_DELETE = "block_group_delete"
    REFRESH_RUNTIME_POLICY = "refresh_runtime_policy"
    REVALIDATE_ON_ACTIVATION = "revalidate_on_activation"
    AUDIT_ONLY = "audit_only"
```

Registry mode: `CREDENTIAL_DEPENDENCY_REGISTRY_MODE=shadow|enforce`, default `shadow`.

- [ ] **Step 1: Write failing descriptor tests**

Cover live Agent, Agent Version, Trigger, Environment, active Session Snapshot, Session→Group, Quickstart, Skill Authoring, aggregate-internal Credential→Group, and legacy compatibility surfaces.

- [ ] **Step 2: Write failing operation-disposition tests**

Assert Agent Version is `REVALIDATE_ON_ACTIVATION`; Session→Group blocks Group archive/delete but only refreshes member mutation; active Session Snapshot blocks referenced Resource archive/delete.

- [ ] **Step 3: Add a deliberate unregistered consumer fixture**

The reverse census must fail when a new typed Credential ID, raw key path, SQL query, or reveal callsite lacks classification.

- [ ] **Step 4: Run focused registry tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_reference_registry.py backend/tests/test_credential_reference_reverse_census.py`

- [ ] **Step 5: Implement Domain descriptors, Application scanner ports, and Infrastructure scanners**

Exception entries require `surface`, `owner`, `reason`, and `removal_condition`.

- [ ] **Step 6: Implement production shadow comparison**

In `shadow`, execute old and new scans, enforce old result, emit only IDs/counts/disposition diff metrics, and never log Snapshot/Environment payloads.

- [ ] **Step 7: Re-run registry and legacy blocker tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_reference_registry.py backend/tests/test_credential_reference_reverse_census.py backend/tests/test_credential_service.py backend/tests/test_organization_credential_blockers.py`

---

### Task 9: Unify Lifecycle, Group Restore, and Transaction Semantics

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/resource_service.py`
- Modify: `backend/app/joysafeter_application/credentials/group_service.py`
- Modify: `backend/app/joysafeter_application/credentials/binding_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Modify: `backend/app/joysafeter_api/api/v1/credential_groups.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_group_service.py`
- Modify: `backend/tests/test_credential_service.py`
- Modify: `backend/tests/test_credential_group_service.py`
- Modify: `backend/tests/test_credentials_api.py`
- Modify: `backend/tests/test_credential_atomic_refresh.py`

**Interfaces:**
- Lock order: Group IDs → `(project_id, protocol)` default scope → Credential IDs → consumer aggregate → policy rows.
- Archive/delete/restore are idempotent by state; create remains protected by unique-name conflict.

- [ ] **Step 1: Add failing lifecycle matrix tests**

Cover archived Resource PATCH rejection, Group archived member mutation rejection, Resource/Group idempotent archive/delete/restore, Group restore endpoint, legacy OAuth restore rejection, and default clearing. With an active Session→Group association, Group archive/delete must fail, while member add/archive/delete must succeed only after URL validation and must persist `REFRESH_RUNTIME_POLICY` impact. Generic Resource and Group-member endpoints must produce the same member-lifecycle decision.

- [ ] **Step 2: Add failing default concurrency test**

Use two DB sessions setting different defaults for the same `(project_id, protocol)` and assert no deadlock plus exactly one final default.

- [ ] **Step 3: Add failing mutation/audit/pending rollback test**

Force Audit insertion failure and assert Credential mutation plus policy pending both roll back.

- [ ] **Step 4: Run focused lifecycle tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_service.py backend/tests/test_credential_group_service.py backend/tests/test_credentials_api.py backend/tests/test_credential_atomic_refresh.py`

- [ ] **Step 5: Implement Application-owned Unit of Work and scope lock**

Use a transaction advisory lock or dedicated scope row for `(project_id, protocol)` before locking current and target defaults.

- [ ] **Step 6: Make network nudge best-effort after commit**

Nudge failure increments a metric and leaves durable pending state; it must not change a successful API result to 500.

- [ ] **Step 7: Re-run focused tests**

Expected: PASS with one commit per mutation.

---

### Task 10: Consolidate the Rust Credential Runtime Store

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mod.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/store.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/record.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/material.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/error.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/model.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/service.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mcp.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/task_identity/material.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/repository_access/material.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/sensitive_material/legacy_v1.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/tests/credential_store_integration.rs`

**Interfaces:**

```rust
impl CredentialStore {
    async fn get_active(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
    ) -> Result<CredentialRecord, CredentialRuntimeError>;

    async fn load_session_mcp_members(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
    ) -> Result<Vec<McpCredentialRecord>, CredentialRuntimeError>;
}
```

- [ ] **Step 1: Add failing Store integration tests**

Use real PostgreSQL rows for model/service/MCP, active/archived/deleted Group, cross-project Session association, missing field, legacy bearer, unknown scheme, and malformed envelope.

- [ ] **Step 2: Run Store tests**

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --test credential_store_integration -- --nocapture`

- [ ] **Step 3: Implement project-scoped Store queries**

`load_session_mcp_members` must join Session→association→Group→Credential and require the same project plus active Group/Resource state.

- [ ] **Step 4: Move managed reveal to `credentials/material.rs`**

Task Identity and Repository Access call only their own adapters over `sensitive_material/legacy_v1.rs`.

- [ ] **Step 5: Migrate Harness and Sandbox orchestration**

Remove direct Credential SQL/decrypt and old names `SecretRow`, `RuntimeSecretBinding`, `VaultCredentialRow`, `VaultCipher`, and `resolve_vault_credentials`.

- [ ] **Step 6: Add AST/cfg-aware SQL architecture guard**

Reject production Credential SQL outside `kernel/credentials/store.rs`; exclude or relocate `#[cfg(test)]` fixtures explicitly.

- [ ] **Step 7: Run full Rust tests**

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml`

---

### Task 11: Linearize All Snapshot Materialization Entry Points

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/snapshot_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/app/joysafeter_api/api/v1/tasks.py`
- Modify: `backend/app/joysafeter_domain/services/agent_trigger_execution.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/snapshot.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs`
- Create: `backend/tests/test_credential_snapshot_linearization.py`
- Create: `backend/app/joysafeter_orchestrator_rs/tests/credential_snapshot_linearization.rs`

**Interfaces:**

```python
async def create_session_from_source(
    command: CreateCredentialAwareSession,
    uow: CredentialUnitOfWork,
) -> JoySafeterSession: ...
```

The command identifies live Agent or pinned Agent Version, Environment override, Group IDs, caller, and request metadata; callers do not prebuild Snapshot dictionaries.

- [ ] **Step 1: Add Python concurrency tests with barriers**

Cover Session/Task/Trigger Snapshot-create vs Credential archive, Snapshot-create vs Group archive, Group member mutation vs Session create, and stale pre-lock references.

- [ ] **Step 2: Add pinned Agent Version activation tests**

Archived/missing referenced Credential must return `CREDENTIAL_STATE_INVALID`/`CREDENTIAL_NOT_FOUND` and create no Session.

- [ ] **Step 3: Run Python linearization tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_snapshot_linearization.py`

- [ ] **Step 4: Move all Python entry points behind Snapshot Application Service**

The service collects references through the Codec, locks Group/Credential/consumer rows, re-reads source versions, retries only changed-reference races, validates Policy, then persists Snapshot/Session/Audit/pending in one transaction.

- [ ] **Step 5: Implement equivalent Rust Scheduler transaction**

Rust Scheduler uses `credentials::snapshot` and `CredentialStore`; it may not call raw `queries::create_session` with a separately built Snapshot.

- [ ] **Step 6: Run Rust linearization test**

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --test credential_snapshot_linearization -- --nocapture`

- [ ] **Step 7: Stress the Python race tests**

Run: `for i in $(seq 1 20); do backend/.venv/bin/pytest -q -x backend/tests/test_credential_snapshot_linearization.py || exit 1; done`

Expected: twenty consecutive passes.

---

### Task 12: Implement E1 Reader-First Reference Codec

**Files:**
- Modify: `backend/app/joysafeter_domain/credentials/references.py`
- Modify: `backend/app/joysafeter_application/credentials/snapshot_service.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_environment.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/reference.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/run_spec.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `frontend/lib/managed/environment-response-parsers.ts`
- Modify: `frontend/types/managed.ts`
- Create: `backend/tests/test_credential_reference_codec.py`
- Modify: `backend/tests/test_environment_credential_refs.py`
- Modify: `frontend/lib/managed/environment-response-parsers.test.ts`

**Interfaces:**

```python
class CredentialReferenceCodec:
    def decode_snapshot(self, raw: object) -> CanonicalCredentialReferences: ...
    def decode_environment(self, raw: object) -> CanonicalEnvironmentReferences: ...
    def encode_snapshot(self, value, *, version: Literal["v1", "v2"]) -> dict: ...
    def encode_environment(self, value, *, version: Literal["v1", "v2"]) -> dict: ...
```

E1 uses `version="v1"` for persistence while all readers accept legacy-v0/v1/v2. Unknown explicit schema fails closed.

- [ ] **Step 1: Add shared fixture-driven codec tests**

Fixtures must include no-schema `secret_ref`, `secret_refs`, top-level `service_credential_id`, `secret_key`, explicit v1, explicit v2, mixed old/new duplicates, malformed IDs, and unknown schema.

- [ ] **Step 2: Run Python, Rust, and Frontend reader tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_reference_codec.py backend/tests/test_environment_credential_refs.py`

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml credentials::reference -- --nocapture`

Run: `cd frontend && bun test lib/managed/environment-response-parsers.test.ts`

- [ ] **Step 3: Implement Python/Rust decoders from the shared contract**

No caller may read registered JSON key paths directly after migration.

- [ ] **Step 4: Keep all persistence writers on v1**

E1 code must prove v2 decode works while `encode_*` defaults to v1 and emits no new persistent key.

- [ ] **Step 5: Add reader-version and persisted-key metrics**

Metrics contain schema version and counts only; never payloads or Material.

- [ ] **Step 6: Re-run focused tests and architecture census**

Expected: dual readers PASS with no v2 writes.

---

### Task 13: Implement E2 Writer Cutover and Frontend Canonical Writes

**Files:**
- Modify: `backend/app/joysafeter_shared/config/settings.py`
- Modify: `deploy/docker-compose.yml`
- Modify: `backend/app/joysafeter_application/credentials/snapshot_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs`
- Modify: `frontend/components/managed/environments-egress-editor.tsx`
- Modify: `frontend/components/managed/environments-egress-editor.test.tsx`
- Modify: `frontend/types/entity-id-architecture.test.ts`
- Create: `backend/tests/test_credential_reference_writer_cutover.py`
- Create: `docs/runbooks/credential-p0-5-reference-cutover.md`

**Interfaces:**
- Server flag: `CREDENTIAL_REFERENCE_WRITE_VERSION=v1|v2`, default `v1`.
- Backend accepts old/new browser input in both modes; persistence shape is controlled only by the server flag.

- [ ] **Step 1: Add failing writer-version tests**

```python
@pytest.mark.parametrize(("version", "expected_key"), [
    ("v1", "secret_refs"),
    ("v2", "environment_credential_ids"),
])
async def test_environment_persistence_follows_server_write_version(version, expected_key, ...):
    saved = await persist_environment(version=version, client_shape="legacy")
    assert expected_key in saved.config
```

- [ ] **Step 2: Add Rust Scheduler writer tests**

Assert v1 flag writes `joysafeter.agent_execution_snapshot.v1`; v2 flag writes v2 and canonical Environment keys.

- [ ] **Step 3: Run writer tests and verify missing flag behavior**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_reference_writer_cutover.py`

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml scheduler -- --nocapture`

- [ ] **Step 4: Implement the server-controlled writer switch in every writer**

Python Session/Task/Trigger paths call Snapshot Service; Rust Scheduler calls the same contract-aware encoder; live Environment persistence uses the server version.

- [ ] **Step 5: Make Frontend dual-read and canonical-write**

Frontend submits `environment_credential_ids` and `credential_field`; stale old clients remain safe because Backend canonicalizes before persistence.

- [ ] **Step 6: Write the E1→E2 runbook**

Runbook must require: all deployed Backend/Worker/Orchestrator/Scheduler versions are dual-reader; unknown-schema metric is zero; E1 has completed; enable v2 on canary; verify new-write counts; then expand. Rollback sets writer flag to v1 but never deploys a v1-only reader.

- [ ] **Step 7: Run focused Backend/Rust/Frontend tests**

Run: `cd frontend && bun test lib/managed/environment-response-parsers.test.ts components/managed/environments-egress-editor.test.tsx types/entity-id-architecture.test.ts && bun run type-check && bun run lint`

---

### Task 14: Execute E3 Resumable Live Environment Backfill

**Files:**
- Create: `backend/scripts/backfill_credential_references.py`
- Create: `backend/tests/test_credential_reference_backfill.py`
- Modify: `backend/scripts/credential_p0_5_preflight.py`
- Create: `docs/runbooks/credential-p0-5-reference-backfill.md`

**Interfaces:**
- Command options: `--dry-run`, `--batch-size`, `--after-id`, `--max-rows`, `--sleep-ms`, `--output-report`.
- Updates only live Environment rows using `updated_at` CAS; never rewrites Agent Version or Session Snapshot history.

- [ ] **Step 1: Add failing backfill tests**

Cover dry-run, idempotence, stable cursor resume, CAS conflict, repeated final sweep, malformed config blocker, duplicate old/new keys, and immutable Snapshot exclusion.

- [ ] **Step 2: Run focused tests**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_reference_backfill.py`

- [ ] **Step 3: Implement small-batch CAS updates**

Counters: `scanned`, `changed`, `unchanged`, `conflicted`, `failed`, `legacy_remaining`. Failure records Environment ID, key path, and error class only.

- [ ] **Step 4: Make malformed rows contract blockers**

Do not clear, skip as success, or quarantine without visibility. `legacy_remaining` and `failed` keep E3 incomplete.

- [ ] **Step 5: Add final-sweep mode**

After the stable cursor reaches the end, start a fresh pass until two consecutive full passes report `changed=0`, `conflicted=0`, `failed=0`, and `legacy_remaining=0`.

- [ ] **Step 6: Write the operational runbook**

Include dry-run, canary batch, pause/resume, metrics, rollback to v1 writer, and proof that historical Snapshots remain unchanged.

- [ ] **Step 7: Verify against a disposable PostgreSQL database**

Run: `backend/.venv/bin/python backend/scripts/backfill_credential_references.py --dry-run --output-report /tmp/credential-backfill.json`

Expected: no Snapshot updates and no sensitive payload in output.

---

### Task 15: Enable Enforce Mode, Architecture Gates, and Release Evidence

**Files:**
- Modify: `backend/tests/test_credential_domain_architecture.py`
- Modify: `backend/tests/test_credential_reference_reverse_census.py`
- Create: `backend/tests/test_credential_runtime_e2e.py`
- Modify: `frontend/lib/i18n/credential-terminology.test.ts`
- Create: `docs/superpowers/evidence/2026-08-16-credential-domain-closure-p0-5.md`
- Modify: `docs/runbooks/credential-p0-5-reference-cutover.md`
- Modify: `docs/runbooks/credential-p0-5-reference-backfill.md`

**Interfaces:**
- Architecture guards allow legacy names/keys only in approved migration, legacy decoder, and compatibility-fixture locations.
- Registry moves from `shadow` to `enforce` only after evidence gates pass.

- [ ] **Step 1: Add final failing architecture guards**

Reject active-path `SecretRow`, `RuntimeSecretBinding`, `VaultCredentialRow`, `VaultCipher`, raw registered key reads, direct managed reveal, and Credential SQL outside approved modules. Do not reject immutable historical Snapshot contents processed by legacy decoders.

- [ ] **Step 2: Add E2E material-boundary tests**

Cover model, MCP, HTTP bearer/header/cookie, Webhook verifier, Repository Access, Task Identity, and explicit Environment Injection. Assert only Environment Injection reaches sandbox env; model/MCP/HTTP material is absent from env, files, argv, logs, Audit, and Snapshot.

- [ ] **Step 3: Run focused Backend architecture/E2E suites**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_domain_contract.py backend/tests/test_credential_domain_core.py backend/tests/test_credential_domain_architecture.py backend/tests/test_credential_reference_registry.py backend/tests/test_credential_reference_reverse_census.py backend/tests/test_credential_snapshot_linearization.py backend/tests/test_credential_runtime_e2e.py`

- [ ] **Step 4: Run complete Rust and Frontend gates**

Run: `cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml`

Run: `cd frontend && bun test && bun run type-check && bun run lint`

- [ ] **Step 5: Run existing Backend regression suites**

Run: `backend/.venv/bin/pytest -q backend/tests/test_credential_service.py backend/tests/test_credential_group_service.py backend/tests/test_credentials_api.py backend/tests/test_environment_credential_refs.py backend/tests/test_session_credential_groups.py backend/tests/test_trigger_webhook_auth_credential.py backend/tests/test_foundation3_task_identity.py backend/tests/test_session_resource_error_contract.py backend/tests/test_quickstart_error_contract.py backend/tests/test_skill_authoring_error_contract.py`

- [ ] **Step 6: Collect shadow and reference evidence**

Require zero old/new dependency semantic diff for at least 24 hours in preproduction, zero synthetic census diff for 288 consecutive five-minute checks, unknown Snapshot schema count zero for active Sessions, E2 v1 new-write count zero, and E3 live Environment legacy count zero.

- [ ] **Step 7: Write the release evidence artifact**

Record commit SHA, image versions, database revision, preflight report hash, shadow interval, writer flag state, backfill counters, test command outputs, rollback floor, and approvers. Do not edit the design specification to store operational evidence.

- [ ] **Step 8: Switch Registry to enforce and verify canary**

Set `CREDENTIAL_DEPENDENCY_REGISTRY_MODE=enforce` on canary, run lifecycle synthetic tests, then expand. Rollback returns to `shadow`; it does not restore removed old business writers.

---

## Execution Order and Review Gates

1. Tasks 1–3 form P0.5-0 and must pass before any preproduction claim of Runtime correctness.
2. Tasks 4–8 establish Domain/Application/Registry boundaries; review before lifecycle mutation changes.
3. Tasks 9–11 establish transaction and Runtime closure; review concurrency and cross-language behavior before reference migration.
4. Task 12 is E1 reader-only and may deploy independently.
5. Task 13 is E2 writer cutover and must not begin until the E1 fleet gate is satisfied.
6. Task 14 is E3 live-data backfill and begins only after E2 new-write telemetry is stable.
7. Task 15 enables final guards and Registry enforcement only after evidence gates pass.

Each task is an independent review checkpoint. Execution sessions must run the task’s focused verification before proceeding and must not commit or push unless the user has explicitly authorized that action.

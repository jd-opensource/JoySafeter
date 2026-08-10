# Secret Reference ID Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every persisted and runtime name-based Secret reference with a project-scoped semantic credential ID, preserve one compatibility release for legacy clients, and make dependency integrity race-safe through a transactionally rebuilt Binding projection.

**Architecture:** Owner configuration is the business source of truth: Agents persist `model_connection_id`, Triggers persist `service_credential_id` plus `credential_field`, and Environments persist `service_credential_ids` plus stable-ID Egress references. `CredentialReferenceResolver` adapts legacy names only at API boundaries, while `CredentialBindingProjector` replaces dependency rows in the same transaction and locks the same Secret rows used by soft deletion. Compatibility deployment uses `dual_read`; the migration release cuts runtime to `id_only`, retains legacy snapshots for rollback, and removes them only in the following contract release.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL, Alembic, pytest; TypeScript, React 19, Next.js 16, TanStack Query, Vitest; Rust 2021, Tokio, SQLx; Docker/Kubernetes deployment scripts.

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-10-secret-reference-id-migration-design.md` as the normative contract.
- Preserve the existing Secret aggregate, `joysafeter_secrets` table, and public `secret_<uuid>` entity ID format.
- Public semantic fields are `model_connection_id`, `service_credential_id`, `service_credential_ids`, and `credential_field`; do not expose a generic public `secret_id` field.
- `ModelConnectionId` must resolve an active, project-owned, LLM-compatible Secret; `ServiceCredentialId` must resolve an active, project-owned Generic Secret.
- Owner semantic ID fields are authoritative. `joysafeter_credential_bindings` is a transactionally rebuilt integrity projection and has no public mutation API.
- Owner writes and Secret soft deletion lock affected Secret rows in ascending UUID order before changing owner data or bindings.
- Physical Secret deletion remains protected by a database foreign key with `ON DELETE RESTRICT`.
- Compatibility names are accepted only by API request adapters and are immediately resolved to IDs; domain and runtime services receive IDs.
- If an ID and legacy name resolve to different rows, reject with `CREDENTIAL_REFERENCE_CONFLICT` before persistence.
- In `dual_read`, ID is primary and a legacy snapshot may be read only when the ID is absent; in `id_only`, runtime name fallback is forbidden.
- The migration release keeps old columns and JSON names for rollback but stops runtime reads and new snapshot writes after cutover.
- No API response, migration report, audit event, metric label, log, or error may contain decrypted credential values.
- Backend commands run from `backend/`; frontend commands run from `frontend/`; Rust commands run from `backend/app/joysafeter_orchestrator_rs/`.
- Use TDD for each task and commit only the files listed by that task.

---

## File Structure

### New Backend Files

- `backend/app/joysafeter_domain/models/joysafeter_credential_binding.py` — Binding projection and resumable migration-run persistence.
- `backend/app/joysafeter_domain/services/joysafeter_credential_reference_resolver.py` — project/kind/field-aware ID and compatibility-name resolution.
- `backend/app/joysafeter_domain/services/joysafeter_credential_binding_projector.py` — deterministic row locking and full owner projection replacement.
- `backend/app/joysafeter_domain/services/joysafeter_credential_dependency_service.py` — stable dependency reads from Binding rows.
- `backend/app/joysafeter_domain/services/joysafeter_credential_reference_backfill_service.py` — resumable owner backfill and result accounting.
- `backend/app/joysafeter_domain/services/joysafeter_credential_cutover_service.py` — cutover readiness and drift gate.
- `backend/app/joysafeter_shared/credential_reference_observability.py` — bounded-cardinality counters, durations, and structured audit payloads.
- `backend/scripts/backfill_credential_references.py` — operator CLI for batched backfill and verification.
- `backend/alembic/versions/20260810_000003_secret_reference_ids.py` — expand migration only; no legacy field removal.

### New Test and Documentation Files

- `backend/tests/test_credential_reference_mode.py`
- `backend/tests/test_models/test_secret_reference_id_migration.py`
- `backend/tests/services/test_credential_reference_resolver.py`
- `backend/tests/services/test_credential_binding_projector.py`
- `backend/tests/services/test_credential_reference_backfill.py`
- `backend/tests/services/test_credential_cutover_gate.py`
- `backend/tests/test_credential_binding_concurrency.py`
- `backend/tests/test_credential_reference_observability.py`
- `backend/app/joysafeter_orchestrator_rs/src/db/queries/credential.rs`
- `docs/runbooks/secret-reference-id-migration.md`

### Existing Files With Focused Changes

- `backend/app/joysafeter_shared/ids.py`, `backend/app/joysafeter_shared/config/settings.py` — semantic ID types and migration mode.
- Agent, Trigger, Environment models/schemas/services/API routes — semantic persistence and API adapters.
- Quickstart and Skill Authoring request paths — semantic model connection contracts.
- `frontend/types/entity-id.ts`, managed request types, selectors, dialogs, pages, and hooks — ID wire values with name labels.
- Rust agent/environment query and runtime builders — ID-only runtime resolution.
- Secret service/API lifecycle paths — Binding-backed dependency checks and shared locking.
- `deploy/.env.example`, deployment manifests, and runbook — explicit rollout and rollback controls.

---

### Task 1: Add Semantic IDs and Reference Mode

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py`
- Modify: `backend/app/joysafeter_shared/config/settings.py`
- Create: `backend/tests/test_credential_reference_mode.py`
- Modify: `backend/tests/test_entity_ids.py`

**Interfaces:**
- Consumes: existing `SecretId`, `EntityId.from_public()`, and `SettingsConfigDict(env_prefix="JOYSAFETER_")`.
- Produces: `CredentialResourceId`, `ModelConnectionId`, `ServiceCredentialId`, `CredentialBindingId`, `CredentialMigrationRunId`, `CredentialReferenceMode`, and `Settings.credential_reference_mode`.

- [ ] **Step 1: Write failing semantic type and mode tests**

```python
def test_semantic_credential_ids_keep_secret_wire_prefix() -> None:
    raw = "secret_018f47f0-7b5b-7f82-8c62-2c34938b38d9"
    assert str(ModelConnectionId.from_public(raw)) == raw
    assert str(ServiceCredentialId.from_public(raw)) == raw
    assert ModelConnectionId.from_public(raw) != ServiceCredentialId.from_public(raw)


def test_reference_mode_defaults_to_dual_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOYSAFETER_CREDENTIAL_REFERENCE_MODE", raising=False)
    assert Settings(_env_file=None).credential_reference_mode is CredentialReferenceMode.DUAL_READ


def test_reference_mode_accepts_id_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOYSAFETER_CREDENTIAL_REFERENCE_MODE", "id_only")
    assert Settings(_env_file=None).credential_reference_mode is CredentialReferenceMode.ID_ONLY
```

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_credential_reference_mode.py tests/test_entity_ids.py -q`

Expected: collection fails because the semantic ID classes and `CredentialReferenceMode` do not exist.

- [ ] **Step 3: Implement exact types and configuration**

Add to `ids.py`:

```python
class CredentialResourceId(SecretId):
    pass


class ModelConnectionId(CredentialResourceId):
    pass


class ServiceCredentialId(CredentialResourceId):
    pass


class CredentialBindingId(EntityId):
    prefix = "credbind_"


class CredentialMigrationRunId(EntityId):
    prefix = "credmig_"
```

Add to `settings.py`:

```python
class CredentialReferenceMode(StrEnum):
    DUAL_READ = "dual_read"
    ID_ONLY = "id_only"


credential_reference_mode: CredentialReferenceMode = Field(
    default=CredentialReferenceMode.DUAL_READ,
)
```

Keep semantic IDs out of `REGISTERED_ENTITY_ID_PREFIXES` because they reuse the registered `secret_` wire prefix; register only the two new physical entity prefixes.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/test_credential_reference_mode.py tests/test_entity_ids.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/ids.py backend/app/joysafeter_shared/config/settings.py backend/tests/test_credential_reference_mode.py backend/tests/test_entity_ids.py
git commit -m "feat(credentials): add semantic reference types"
```

---

### Task 2: Add Expand Migration and Persistence Models

**Files:**
- Create: `backend/alembic/versions/20260810_000003_secret_reference_ids.py`
- Create: `backend/app/joysafeter_domain/models/joysafeter_credential_binding.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_agent.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_trigger.py`
- Modify: `backend/app/joysafeter_domain/models/__init__.py`
- Create: `backend/tests/test_models/test_secret_reference_id_migration.py`

**Interfaces:**
- Consumes: `SecretId`, `CredentialBindingId`, `CredentialMigrationRunId`, current Alembic head `20260807_000002`, and UUID-backed SQLAlchemy entity ID columns.
- Produces: nullable `JoySafeterAgent.model_connection_id`, nullable `JoySafeterTrigger.service_credential_id`, `CredentialBinding`, and `CredentialReferenceMigrationRun`.

- [ ] **Step 1: Write failing migration/model tests**

```python
def test_expand_revision_has_expected_lineage() -> None:
    module = importlib.import_module("alembic.versions.20260810_000003_secret_reference_ids")
    assert module.revision == "20260810_000003"
    assert module.down_revision == "20260807_000002"


async def test_binding_rejects_duplicate_owner_slot(db_session, generic_secret, agent) -> None:
    first = CredentialBinding.for_agent_model(agent=agent, credential=generic_secret)
    db_session.add_all([first, CredentialBinding.for_agent_model(agent=agent, credential=generic_secret)])
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

Also inspect the migration operations and assert these exact objects exist: Agent/Trigger UUID columns, composite project/credential foreign key, unique owner-slot constraint, dependency and owner indexes, and migration-run table.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_models/test_secret_reference_id_migration.py -q`

Expected: import and model lookup fail because the revision and ORM models are absent.

- [ ] **Step 3: Implement expand-only schema**

Use these persistence contracts:

```python
class CredentialBinding(JoySafeterBaseModel):
    __tablename__ = "joysafeter_credential_bindings"

    id: Mapped[CredentialBindingId]
    project_id: Mapped[str]
    credential_id: Mapped[SecretId]
    consumer_type: Mapped[str]
    consumer_id: Mapped[uuid.UUID]
    binding_purpose: Mapped[str]
    binding_slot: Mapped[str]


class CredentialReferenceMigrationRun(JoySafeterBaseModel):
    __tablename__ = "joysafeter_credential_reference_migration_runs"

    id: Mapped[CredentialMigrationRunId]
    consumer_type: Mapped[str]
    high_water_mark: Mapped[uuid.UUID | None]
    status: Mapped[str]
    scanned_count: Mapped[int]
    backfilled_count: Mapped[int]
    unresolved_count: Mapped[int]
    conflict_count: Mapped[int]
    retry_count: Mapped[int]
    result_summary: Mapped[dict[str, object]]
```

The Alembic revision must:

1. Add nullable `model_connection_id UUID` to `joysafeter_agents`.
2. Add nullable `service_credential_id UUID` to `joysafeter_triggers`.
3. Add `UNIQUE (project_id, id)` to `joysafeter_secrets` if no equivalent constraint exists.
4. Create `joysafeter_credential_bindings` with `FOREIGN KEY (project_id, credential_id) REFERENCES joysafeter_secrets(project_id, id) ON DELETE RESTRICT`.
5. Add `UNIQUE (consumer_type, consumer_id, binding_purpose, binding_slot)`, `INDEX (project_id, credential_id)`, and `INDEX (consumer_type, consumer_id)`.
6. Create the migration-run table without changing or dropping legacy columns.

The downgrade drops only objects introduced by this revision in reverse dependency order.

- [ ] **Step 4: Run GREEN and migration round-trip tests**

Run: `cd backend && uv run pytest tests/test_models/test_secret_reference_id_migration.py -q`

Expected: ORM metadata and upgrade/downgrade checks pass.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260810_000003_secret_reference_ids.py backend/app/joysafeter_domain/models/joysafeter_credential_binding.py backend/app/joysafeter_domain/models/joysafeter_agent.py backend/app/joysafeter_domain/models/joysafeter_trigger.py backend/app/joysafeter_domain/models/__init__.py backend/tests/test_models/test_secret_reference_id_migration.py
git commit -m "feat(credentials): add reference ID persistence"
```

---

### Task 3: Build the Shared Credential Reference Resolver

**Files:**
- Create: `backend/app/joysafeter_domain/services/joysafeter_credential_reference_resolver.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_secret_service.py`
- Create: `backend/tests/services/test_credential_reference_resolver.py`

**Interfaces:**
- Consumes: `ModelConnectionId`, `ServiceCredentialId`, `SecretId`, project ID, Secret kind/soft-delete state, compatibility ID/name pairs, and decrypted values only for explicit runtime value resolution.
- Produces: `ResolvedCredentialReference`, `resolve_model_connection()`, `resolve_service_credential()`, `resolve_compatibility_reference()`, and `resolve_field_value()`.

- [ ] **Step 1: Write failing resolver contract tests**

```python
async def test_compatibility_name_resolves_to_semantic_id(resolver, llm_secret) -> None:
    result = await resolver.resolve_compatibility_reference(
        project_id=llm_secret.project_id,
        purpose=CredentialPurpose.AGENT_MODEL_CONNECTION,
        credential_id=None,
        legacy_name=llm_secret.name,
    )
    assert result.credential_id == ModelConnectionId.from_uuid(llm_secret.id.uuid)
    assert result.resolved_from is ReferenceSource.LEGACY_NAME


async def test_id_name_conflict_is_rejected(resolver, llm_secret, second_llm_secret) -> None:
    with pytest.raises(RequestValidationAppError) as exc:
        await resolver.resolve_compatibility_reference(
            project_id=llm_secret.project_id,
            purpose=CredentialPurpose.AGENT_MODEL_CONNECTION,
            credential_id=ModelConnectionId.from_uuid(llm_secret.id.uuid),
            legacy_name=second_llm_secret.name,
        )
    assert exc.value.code == "CREDENTIAL_REFERENCE_CONFLICT"
```

Add cases for wrong project, soft-deleted resource, wrong kind, missing field, blank Webhook field value, and `id_only` rejecting an internal name-only call.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/services/test_credential_reference_resolver.py -q`

Expected: module import fails.

- [ ] **Step 3: Implement resolver interfaces**

```python
class CredentialPurpose(StrEnum):
    AGENT_MODEL_CONNECTION = "agent_model_connection"
    ENVIRONMENT_INJECTED_CREDENTIAL = "environment_injected_credential"
    ENVIRONMENT_EGRESS_AUTHENTICATION = "environment_egress_authentication"
    TRIGGER_WEBHOOK_AUTHENTICATION = "trigger_webhook_authentication"


@dataclass(frozen=True)
class ResolvedCredentialReference(Generic[CredentialIdT]):
    credential_id: CredentialIdT
    secret: JoySafeterSecret
    resolved_from: ReferenceSource


async def resolve_compatibility_reference(
    self,
    *,
    project_id: str,
    purpose: CredentialPurpose,
    credential_id: ModelConnectionId | ServiceCredentialId | None,
    legacy_name: str | None,
    credential_field: str | None = None,
) -> ResolvedCredentialReference[ModelConnectionId | ServiceCredentialId]:
    return await self._resolve_reference(
        project_id=project_id,
        purpose=purpose,
        credential_id=credential_id,
        legacy_name=legacy_name,
        credential_field=credential_field,
        allow_legacy_name=True,
    )

async def resolve_field_value(
    self,
    *,
    project_id: str,
    credential_id: ServiceCredentialId,
    credential_field: str,
    require_nonblank: bool,
) -> str:
    resolved = await self.resolve_service_credential(
        project_id=project_id,
        credential_id=credential_id,
        credential_field=credential_field,
    )
    value = self.secret_service.get_secret_data(resolved.secret)[credential_field]
    if require_nonblank and not value.strip():
        raise RequestValidationAppError(code="CREDENTIAL_FIELD_EMPTY", message="Credential field is empty")
    return value
```

Implement `SecretService.get_active_secret_by_id_for_update(secret_id, project_id)` with `SELECT id, project_id, kind, provider, protocol, data, deleted_at FROM joysafeter_secrets WHERE id = :secret_id AND project_id = :project_id AND deleted_at IS NULL FOR UPDATE`. Name lookup is called only by `resolve_compatibility_reference`; direct semantic methods never accept a name.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/services/test_credential_reference_resolver.py tests/test_secret_connectivity.py -q`

Expected: all selected tests pass and no assertion observes a decrypted value in exception data.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_credential_reference_resolver.py backend/app/joysafeter_domain/services/joysafeter_secret_service.py backend/tests/services/test_credential_reference_resolver.py
git commit -m "feat(credentials): centralize semantic reference resolution"
```

---

### Task 4: Build Transactional Binding Projection

**Files:**
- Create: `backend/app/joysafeter_domain/services/joysafeter_credential_binding_projector.py`
- Create: `backend/app/joysafeter_domain/services/joysafeter_credential_dependency_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_secret_service.py`
- Create: `backend/tests/services/test_credential_binding_projector.py`
- Modify: `backend/tests/test_secret_lifecycle_active_dependencies.py`

**Interfaces:**
- Consumes: fully validated `CredentialBindingSpec` values derived from final owner configuration and a caller-owned SQLAlchemy transaction.
- Produces: `replace_owner_bindings()`, `list_dependencies()`, deterministic Secret row locking, and Binding-backed soft-delete checks.

- [ ] **Step 1: Write failing projection and lifecycle tests**

```python
async def test_replace_owner_bindings_is_deterministic(projector, agent, llm_secret) -> None:
    spec = CredentialBindingSpec.agent_model(agent.id, llm_secret.id)
    await projector.replace_owner_bindings(
        project_id=agent.project_id,
        consumer_type=CredentialConsumerType.AGENT,
        consumer_id=agent.id.uuid,
        bindings=(spec,),
    )
    await projector.replace_owner_bindings(
        project_id=agent.project_id,
        consumer_type=CredentialConsumerType.AGENT,
        consumer_id=agent.id.uuid,
        bindings=(spec,),
    )
    assert await binding_rows(agent.id.uuid) == [spec]


async def test_soft_delete_uses_binding_projection(secret_service, binding, generic_secret) -> None:
    with pytest.raises(ConflictError) as exc:
        await secret_service.soft_delete_secret(generic_secret.id, project_id=generic_secret.project_id)
    assert exc.value.code == "SECRET_HAS_ACTIVE_DEPENDENCIES"
```

Add a spy assertion that multi-credential replacement locks credential UUIDs in sorted order before deleting and inserting Binding rows.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/services/test_credential_binding_projector.py tests/test_secret_lifecycle_active_dependencies.py -q`

Expected: projector import fails and lifecycle code still scans owner name fields.

- [ ] **Step 3: Implement projector and dependency service**

```python
@dataclass(frozen=True, order=True)
class CredentialBindingSpec:
    credential_id: SecretId
    binding_purpose: CredentialPurpose
    binding_slot: str


async def replace_owner_bindings(
    self,
    *,
    project_id: str,
    consumer_type: CredentialConsumerType,
    consumer_id: uuid.UUID,
    bindings: Sequence[CredentialBindingSpec],
) -> None:
    credential_ids = sorted({binding.credential_id for binding in bindings}, key=lambda item: item.uuid)
    await self._lock_active_credentials(project_id=project_id, credential_ids=credential_ids)
    await self._delete_owner_projection(consumer_type=consumer_type, consumer_id=consumer_id)
    self.db.add_all(self._rows(project_id, consumer_type, consumer_id, bindings))


async def list_dependencies(
    self, *, project_id: str, credential_id: SecretId
) -> Sequence[CredentialDependency]:
    rows = await self.db.scalars(
        select(CredentialBinding)
        .where(
            CredentialBinding.project_id == project_id,
            CredentialBinding.credential_id == credential_id,
        )
        .order_by(
            CredentialBinding.consumer_type,
            CredentialBinding.consumer_id,
            CredentialBinding.binding_purpose,
            CredentialBinding.binding_slot,
        )
    )
    return tuple(CredentialDependency.from_binding(row) for row in rows)
```

`SecretService.soft_delete_secret()` must lock the Secret row first, query only `CredentialDependencyService`, and reject while any Binding exists. Hard delete relies on the FK and maps integrity failure to the same public conflict contract.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/services/test_credential_binding_projector.py tests/test_secret_lifecycle_active_dependencies.py tests/test_secret_vault_name_soft_delete_index.py -q`

Expected: projection replacement, stable ordering, and Binding-backed lifecycle checks pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_credential_binding_projector.py backend/app/joysafeter_domain/services/joysafeter_credential_dependency_service.py backend/app/joysafeter_domain/services/joysafeter_secret_service.py backend/tests/services/test_credential_binding_projector.py backend/tests/test_secret_lifecycle_active_dependencies.py
git commit -m "feat(credentials): add transactional binding projection"
```

### Task 5: Migrate Agent to `model_connection_id`

**Files:**
- Modify: `backend/app/joysafeter_domain/models/joysafeter_agent.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_agent.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/agents.py`
- Modify: `backend/tests/test_agent_schema_contract.py`
- Modify: `backend/tests/test_llm_agent_compatibility.py`
- Modify: `backend/tests/test_agent_lifecycle_active_tasks.py`

**Interfaces:**
- Consumes: `CredentialReferenceResolver.resolve_compatibility_reference()`, `CredentialBindingProjector.replace_owner_bindings()`, `ModelConnectionId`, and `CredentialPurpose.AGENT_MODEL_CONNECTION`.
- Produces: Agent create/update/response contracts with `model_connection_id`, rollback-only `secret_ref`, and an Agent service that persists and projects only the resolved ID.

- [ ] **Step 1: Write failing Agent ID contract tests**

```python
async def test_create_agent_accepts_model_connection_id(client, llm_secret) -> None:
    response = await client.post(
        "/api/v1/agents",
        json=agent_payload(model_connection_id=str(llm_secret.id)),
    )
    assert response.status_code == 201
    assert response.json()["model_connection_id"] == str(llm_secret.id)
    stored = await load_agent(response.json()["id"])
    assert stored.model_connection_id == llm_secret.id


async def test_legacy_agent_name_is_adapted_before_service(client, llm_secret, agent_service_spy) -> None:
    response = await client.post("/api/v1/agents", json=agent_payload(secret_ref=llm_secret.name))
    assert response.status_code == 201
    assert agent_service_spy.create.await_args.kwargs["model_connection_id"] == llm_secret.id
    assert "secret_ref" not in agent_service_spy.create.await_args.kwargs
```

Add update tests for ID/name equality, conflict rejection, wrong project/kind, explicit null unbinding, active-task rebinding protection, and one Binding row with slot `model`.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_agent_schema_contract.py tests/test_llm_agent_compatibility.py tests/test_agent_lifecycle_active_tasks.py -q`

Expected: the API ignores/rejects `model_connection_id` and service signatures still accept `secret_ref`.

- [ ] **Step 3: Implement Agent semantic ownership**

Use these request and service contracts:

```python
class AgentCreateRequest(BaseModel):
    model_connection_id: ModelConnectionId | None = None
    secret_ref: str | None = Field(default=None, deprecated=True)


class AgentUpdateRequest(BaseModel):
    model_connection_id: ModelConnectionId | None = None
    secret_ref: str | None = Field(default=None, deprecated=True)


async def create(
    self,
    *,
    model_connection_id: ModelConnectionId | None,
    legacy_secret_ref_snapshot: str | None,
    **agent_fields: object,
) -> JoySafeterAgent:
    agent = JoySafeterAgent(
        model_connection_id=model_connection_id,
        secret_ref=legacy_secret_ref_snapshot,
        **agent_fields,
    )
    self.db.add(agent)
    await self.db.flush()
    return agent
```

The API adapter calls the resolver and passes only the resolved ID plus an optional rollback snapshot. The service writes `model_connection_id`, writes `secret_ref` only while mode is `dual_read`, flushes the Agent, then calls:

```python
await projector.replace_owner_bindings(
    project_id=agent.project_id,
    consumer_type=CredentialConsumerType.AGENT,
    consumer_id=agent.id.uuid,
    bindings=(() if agent.model_connection_id is None else (
        CredentialBindingSpec(
            credential_id=agent.model_connection_id,
            binding_purpose=CredentialPurpose.AGENT_MODEL_CONNECTION,
            binding_slot="model",
        ),
    )),
)
```

Agent response serializers expose `model_connection_id`; `secret_ref` remains only as a deprecated compatibility response during this release. Model metadata helpers resolve by ID and never key caches by name.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/test_agent_schema_contract.py tests/test_llm_agent_compatibility.py tests/test_agent_lifecycle_active_tasks.py tests/test_agent_environment_ref_validation.py -q`

Expected: all selected Agent tests pass with exact ID persistence and projection assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/models/joysafeter_agent.py backend/app/joysafeter_domain/schemas/joysafeter_agent.py backend/app/joysafeter_domain/services/joysafeter_agent_service.py backend/app/joysafeter_api/api/v1/agents.py backend/tests/test_agent_schema_contract.py backend/tests/test_llm_agent_compatibility.py backend/tests/test_agent_lifecycle_active_tasks.py
git commit -m "feat(agents): persist model connection IDs"
```

---

### Task 6: Migrate Trigger Webhook Authentication

**Files:**
- Modify: `backend/app/joysafeter_domain/models/joysafeter_trigger.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_trigger.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_service.py`
- Modify: `backend/tests/test_trigger_schema_contract.py`
- Modify: `backend/tests/test_trigger_update_validation.py`
- Modify: `backend/tests/test_trigger_http_e2e_contract.py`

**Interfaces:**
- Consumes: `ServiceCredentialId`, resolver field validation, projector, and `CredentialPurpose.TRIGGER_WEBHOOK_AUTHENTICATION`.
- Produces: `service_credential_id` and `credential_field` API semantics, ID-based runtime Webhook value resolution, and slot `webhook` Binding projection.

- [ ] **Step 1: Write failing Trigger semantic tests**

```python
async def test_webhook_trigger_persists_service_credential_id(client, generic_secret) -> None:
    response = await client.post(
        "/api/v1/triggers",
        json=webhook_payload(
            service_credential_id=str(generic_secret.id),
            credential_field="WEBHOOK_SECRET",
        ),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["service_credential_id"] == str(generic_secret.id)
    assert body["credential_field"] == "WEBHOOK_SECRET"


async def test_webhook_runtime_resolves_by_id(webhook_auth_service, trigger, secret_service_spy) -> None:
    await webhook_auth_service.resolve_webhook_secret(trigger)
    secret_service_spy.get_secret_by_name.assert_not_awaited()
    secret_service_spy.get_active_secret_by_id.assert_awaited_once()
```

Add update-only-field, legacy conflict, missing field, blank value, wrong kind/project, null-unbind, and single Binding slot tests.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_trigger_schema_contract.py tests/test_trigger_update_validation.py tests/test_trigger_http_e2e_contract.py -q`

Expected: semantic request fields are rejected and runtime still resolves `secret_ref`.

- [ ] **Step 3: Implement Trigger semantic contracts**

```python
class TriggerCreateRequest(BaseModel):
    service_credential_id: ServiceCredentialId | None = None
    credential_field: str | None = None
    secret_ref: str | None = Field(default=None, deprecated=True)
    secret_key: str | None = Field(default=None, deprecated=True)


@dataclass(frozen=True)
class TriggerUpdatePlan:
    fields: dict[str, object]
    service_credential_id_to_verify: ServiceCredentialId | None
    credential_field_to_verify: str | None
    replace_credential_binding: bool
    recompute_next_run: bool
    is_reenable: bool
```

API compatibility maps `secret_key` to `credential_field`; supplying both with different values produces `CREDENTIAL_REFERENCE_CONFLICT`. `WebhookAuthService.resolve_webhook_secret()` calls:

```python
return await resolver.resolve_field_value(
    project_id=trigger.project_id,
    credential_id=ServiceCredentialId.from_uuid(trigger.service_credential_id.uuid),
    credential_field=trigger.secret_key or "WEBHOOK_SECRET",
    require_nonblank=True,
)
```

Persist `service_credential_id`; retain `secret_ref`/`secret_key` snapshots only in `dual_read`; rebuild one `trigger_webhook_authentication` Binding with slot `webhook` in the same transaction.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/test_trigger_schema_contract.py tests/test_trigger_update_validation.py tests/test_trigger_http_e2e_contract.py tests/test_trigger_webhook_contract.py tests/test_trigger_webhook_route_contract.py -q`

Expected: all selected Trigger tests pass and runtime performs no name lookup.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/models/joysafeter_trigger.py backend/app/joysafeter_domain/schemas/joysafeter_trigger.py backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py backend/app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py backend/app/joysafeter_domain/services/joysafeter_trigger_service.py backend/tests/test_trigger_schema_contract.py backend/tests/test_trigger_update_validation.py backend/tests/test_trigger_http_e2e_contract.py
git commit -m "feat(triggers): use service credential IDs"
```

---

### Task 7: Migrate Environment and Egress References

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py`
- Modify: `backend/tests/test_entity_ids.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_environment.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/tests/test_environment_ref_boundary.py`
- Modify: `backend/tests/test_environment_egress_service_schema.py`
- Modify: `backend/tests/test_environment_lifecycle_active_sessions.py`

**Interfaces:**
- Consumes: `ServiceCredentialId`, resolver, projector, current `secret_refs`/`credential_ref` compatibility inputs, and Environment JSON persistence.
- Produces: `EgressServiceId`, `service_credential_ids`, per-Egress `service_credential_id`/`credential_field`, deterministic extraction, and stable Binding slots.

- [ ] **Step 1: Write failing Environment ID and stable-slot tests**

```python
def test_egress_service_generates_stable_id_once() -> None:
    service = EgressService.model_validate(legacy_egress_service(credential_ref="payments-prod"))
    round_tripped = EgressService.model_validate(service.model_dump(mode="json"))
    assert str(service.id).startswith("egress_")
    assert round_tripped.id == service.id


async def test_reordering_egress_keeps_binding_identity(update_environment, environment) -> None:
    before = await binding_slots(environment.id)
    await update_environment(reversed(environment.config["egress_services"]))
    assert await binding_slots(environment.id) == before
```

Add tests for direct ID deduplication, compatibility-name conversion, ID/name conflict, wrong kind/project, missing field, and complete replacement of direct/Egress Binding rows.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_environment_ref_boundary.py tests/test_environment_egress_service_schema.py tests/test_environment_lifecycle_active_sessions.py -q`

Expected: schemas reject semantic fields and Binding identity changes with list position.

- [ ] **Step 3: Implement semantic Environment JSON**

Add the physical slot ID:

```python
class EgressServiceId(EntityId):
    prefix = "egress_"
```

Use these schemas:

```python
class EgressService(BaseModel):
    id: EgressServiceId = Field(default_factory=EgressServiceId.new)
    service_credential_id: ServiceCredentialId | None = None
    credential_field: str | None = None
    credential_ref: str | None = Field(default=None, deprecated=True)


class EnvironmentConfig(BaseModel):
    service_credential_ids: list[ServiceCredentialId] = Field(default_factory=list)
    secret_refs: list[str] = Field(default_factory=list, deprecated=True)
    egress_services: list[EgressService] = Field(default_factory=list)
```

Replace name extraction with:

```python
def extract_environment_credential_bindings(
    config: EnvironmentConfig,
) -> Sequence[CredentialBindingSpec]:
    direct = {
        CredentialBindingSpec(item, CredentialPurpose.ENVIRONMENT_INJECTED_CREDENTIAL, str(item))
        for item in config.service_credential_ids
    }
    egress = {
        CredentialBindingSpec(
            service.service_credential_id,
            CredentialPurpose.ENVIRONMENT_EGRESS_AUTHENTICATION,
            str(service.id),
        )
        for service in config.egress_services
        if service.service_credential_id is not None
    }
    return tuple(sorted(direct | egress))
```

The API adapter resolves legacy direct and Egress names before calling the service. The service persists semantic JSON, writes legacy snapshots only in `dual_read`, and rebuilds all Environment bindings after flush within the same transaction.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/test_environment_ref_boundary.py tests/test_environment_egress_service_schema.py tests/test_environment_lifecycle_active_sessions.py tests/test_agent_environment_ref_validation.py -q`

Expected: all selected Environment tests pass; reordering does not alter Binding slots.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/ids.py backend/tests/test_entity_ids.py backend/app/joysafeter_domain/schemas/joysafeter_environment.py backend/app/joysafeter_domain/services/joysafeter_environment_service.py backend/app/joysafeter_api/api/v1/environments.py backend/tests/test_environment_ref_boundary.py backend/tests/test_environment_egress_service_schema.py backend/tests/test_environment_lifecycle_active_sessions.py
git commit -m "feat(environments): persist credential IDs"
```

---

### Task 8: Migrate Quickstart and Skill Authoring Contracts

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/quickstart.py`
- Modify: `backend/app/joysafeter_api/api/v1/skills_ai_authoring.py`
- Modify: `backend/tests/test_quickstart_error_contract.py`
- Modify: `backend/tests/test_skill_authoring_error_contract.py`
- Modify: `backend/tests/test_llm_secret_catalog.py`

**Interfaces:**
- Consumes: `ModelConnectionId` and `CredentialReferenceResolver.resolve_compatibility_reference()`.
- Produces: Quickstart/Skill Authoring request models using `model_connection_id`, with deprecated `secret_ref` accepted only by route adapters.

- [ ] **Step 1: Write failing request-boundary tests**

```python
async def test_quickstart_uses_model_connection_id(client, llm_secret, secret_service_spy) -> None:
    response = await client.post(
        "/api/v1/quickstart/chat",
        json=quickstart_payload(model_connection_id=str(llm_secret.id)),
    )
    assert response.status_code == 200
    secret_service_spy.get_secret_by_name.assert_not_awaited()


async def test_skill_authoring_rejects_conflicting_id_and_name(client, llm_secret, second_llm_secret) -> None:
    response = await client.post(
        "/api/v1/skills/ai-authoring/chat",
        json=authoring_payload(
            model_connection_id=str(llm_secret.id),
            secret_ref=second_llm_secret.name,
        ),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "CREDENTIAL_REFERENCE_CONFLICT"
```

Add legacy-name success, wrong project/provider compatibility, and error-data semantic field tests.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_quickstart_error_contract.py tests/test_skill_authoring_error_contract.py tests/test_llm_secret_catalog.py -q`

Expected: request models require/use `secret_ref` and direct name lookup spies are called.

- [ ] **Step 3: Implement ID-first request adapters**

```python
class QuickstartChatRequest(BaseModel):
    model_connection_id: ModelConnectionId | None = None
    secret_ref: str | None = Field(default=None, deprecated=True)


class AuthoringChatRequest(BaseModel):
    model_connection_id: ModelConnectionId | None = None
    secret_ref: str | None = Field(default=None, deprecated=True)
```

Both routes resolve with `CredentialPurpose.AGENT_MODEL_CONNECTION`, pass `resolved.secret` to existing provider/profile logic, and report `model_connection_id` in new error data. Compatibility errors may additionally include `secret_ref` only when that field was supplied by the caller.

- [ ] **Step 4: Run GREEN tests**

Run: `cd backend && uv run pytest tests/test_quickstart_error_contract.py tests/test_skill_authoring_error_contract.py tests/test_llm_secret_catalog.py -q`

Expected: selected tests pass and direct route-level `get_secret_by_name()` calls are gone.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_api/api/v1/quickstart.py backend/app/joysafeter_api/api/v1/skills_ai_authoring.py backend/tests/test_quickstart_error_contract.py backend/tests/test_skill_authoring_error_contract.py backend/tests/test_llm_secret_catalog.py
git commit -m "feat(credentials): migrate authoring requests to IDs"
```

---

### Task 9: Move Frontend Selectors and Payloads to IDs

**Files:**
- Modify: `frontend/types/entity-id.ts`
- Modify: `frontend/types/agent.ts`
- Modify: `frontend/types/managed.ts`
- Modify: `frontend/lib/managed/triggers.ts`
- Modify: `frontend/hooks/managed/use-quickstart-chat.ts`
- Modify: `frontend/hooks/managed/use-skill-authoring.ts`
- Modify: `frontend/lib/managed/quickstart-create.ts`
- Modify: `frontend/components/managed/llm/compatible-secret-picker.tsx`
- Modify: `frontend/components/managed/shared/service-credential-select.tsx`
- Modify: `frontend/app/managed/agents/components/create-agent-dialog.tsx`
- Modify: `frontend/app/managed/agents/[agentId]/edit/page.tsx`
- Modify: `frontend/components/managed/triggers/create-trigger-dialog.tsx`
- Modify: `frontend/components/managed/environments-egress-editor.tsx`
- Modify: focused tests adjacent to every changed component/hook

**Interfaces:**
- Consumes: metadata-only Secret list items `{ id, name, kind, keys }` and backend semantic request/response contracts.
- Produces: branded `ModelConnectionId`/`ServiceCredentialId`, selectors whose option value is an ID and label is a name, and ID-only new-client payloads.

- [ ] **Step 1: Write failing wire-value tests**

```tsx
it('uses credential ID as the selector value and keeps name as the label', async () => {
  render(<CompatibleSecretPicker value={null} onValueChange={onValueChange} />)
  await user.click(screen.getByRole('combobox'))
  await user.click(screen.getByText('OpenAI Production'))
  expect(onValueChange).toHaveBeenCalledWith(asModelConnectionId('secret_018f47f0-7b5b-7f82-8c62-2c34938b38d9'))
})


it('posts semantic IDs without legacy names', async () => {
  await submitAgentForm({ modelConnectionId: secret.id })
  expect(managedPostMock).toHaveBeenCalledWith('/agents', expect.objectContaining({
    model_connection_id: secret.id,
  }))
  expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('secret_ref')
})
```

Add equivalent Trigger, Environment direct/Egress, Quickstart, Skill Authoring, unavailable historical ID, metadata-only field selection, and ID/name conflict UI tests.

- [ ] **Step 2: Run RED tests**

Run: `cd frontend && bun run test -- types/entity-id.test.ts app/managed/agents/components/create-agent-dialog.test.tsx 'app/managed/agents/[agentId]/edit/page.test.tsx' components/managed/triggers/create-trigger-dialog.test.tsx components/managed/environments-egress-editor.test.tsx hooks/managed/use-quickstart-chat.test.tsx hooks/managed/use-skill-authoring.test.tsx`

Expected: callbacks and payloads still carry Secret names.

- [ ] **Step 3: Implement branded semantic IDs and ID payloads**

```typescript
declare const modelConnectionIdBrand: unique symbol
declare const serviceCredentialIdBrand: unique symbol

export type ModelConnectionId = SecretId & { readonly [modelConnectionIdBrand]: true }
export type ServiceCredentialId = SecretId & { readonly [serviceCredentialIdBrand]: true }

export const asModelConnectionId = (value: SecretId): ModelConnectionId => value as ModelConnectionId
export const asServiceCredentialId = (value: SecretId): ServiceCredentialId => value as ServiceCredentialId
```

Update controlled selector contracts to:

```typescript
type CredentialOption = Readonly<{
  id: ModelConnectionId | ServiceCredentialId
  name: string
  keys: readonly string[]
}>

type CredentialSelectProps<Id> = Readonly<{
  value: Id | null
  onValueChange: (value: Id | null) => void
}>
```

Use `option.id` as every Select value and `option.name` as visible text. New payloads emit only semantic fields. Keep an unavailable selected ID visible with an invalid-state label; never fetch plaintext to populate field choices.

- [ ] **Step 4: Run GREEN and static checks**

Run: `cd frontend && bun run test -- types/entity-id.test.ts app/managed/agents/components/create-agent-dialog.test.tsx 'app/managed/agents/[agentId]/edit/page.test.tsx' components/managed/triggers/create-trigger-dialog.test.tsx components/managed/environments-egress-editor.test.tsx hooks/managed/use-quickstart-chat.test.tsx hooks/managed/use-skill-authoring.test.tsx && bun run type-check && bun run lint`

Expected: selected tests, TypeScript checking, and lint pass; existing baseline warnings may remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/types/entity-id.ts frontend/types/agent.ts frontend/types/managed.ts frontend/lib/managed/triggers.ts frontend/hooks/managed/use-quickstart-chat.ts frontend/hooks/managed/use-skill-authoring.ts frontend/lib/managed/quickstart-create.ts frontend/components/managed/llm/compatible-secret-picker.tsx frontend/components/managed/shared/service-credential-select.tsx frontend/app/managed/agents/components/create-agent-dialog.tsx frontend/app/managed/agents/[agentId]/edit/page.tsx frontend/components/managed/triggers/create-trigger-dialog.tsx frontend/components/managed/environments-egress-editor.tsx frontend/types/entity-id.test.ts frontend/app/managed/agents/components/create-agent-dialog.test.tsx frontend/app/managed/agents/[agentId]/edit/page.test.tsx frontend/components/managed/triggers/create-trigger-dialog.test.tsx frontend/components/managed/environments-egress-editor.test.tsx frontend/hooks/managed/use-quickstart-chat.test.tsx frontend/hooks/managed/use-skill-authoring.test.tsx
git commit -m "feat(frontend): send semantic credential IDs"
```

### Task 10: Switch Rust Runtime Resolution to IDs

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/ids.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/models.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/mod.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/agent.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/db/queries/credential.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`

**Interfaces:**
- Consumes: database `model_connection_id`, Environment `service_credential_ids`, Egress `service_credential_id`/`credential_field`, current project ID, and encrypted Secret rows.
- Produces: `CredentialResourceId`, `CredentialStore`, project-scoped ID queries, and zero runtime SQL predicates on Secret names.

- [ ] **Step 1: Write failing Rust ID-only tests**

```rust
#[tokio::test]
async fn agent_secret_query_is_project_scoped_by_id() {
    let row = store
        .get_active_credential(project_id, ModelConnectionId(secret_id))
        .await
        .unwrap();
    assert_eq!(row.id, secret_id);
    assert_eq!(row.project_id, project_id);
}

#[test]
fn environment_reference_extraction_ignores_legacy_names() {
    let config = json!({
        "service_credential_ids": [secret_public_id()],
        "secret_refs": ["legacy-name"]
    });
    assert_eq!(extract_service_credential_ids(&config).unwrap(), vec![secret_uuid()]);
}
```

Add SQL text assertions that runtime credential queries contain `id = $2`, `project_id = $1`, and `deleted_at IS NULL`, and do not contain `name =` or JSON legacy keys.

- [ ] **Step 2: Run RED tests**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test db::queries::credential kernel::harness_input_builder kernel::sandbox_resolver`

Expected: missing module/types and existing name-based test expectations fail.

- [ ] **Step 3: Implement Rust semantic store**

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct ModelConnectionId(pub Uuid);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct ServiceCredentialId(pub Uuid);

#[async_trait]
pub trait CredentialStore: Send + Sync {
    async fn get_active_credential(
        &self,
        project_id: &str,
        credential_id: Uuid,
    ) -> Result<Option<CredentialRow>, sqlx::Error>;
}
```

The SQL implementation is exactly project- and ID-scoped:

```sql
SELECT id, project_id, kind, provider, protocol, data
FROM joysafeter_secrets
WHERE project_id = $1 AND id = $2 AND deleted_at IS NULL
```

Change `JoySafeterAgent.secret_ref` runtime use to `model_connection_id: Option<Uuid>`. `HarnessInputBuilder` loads Agent and Environment credentials by ID; `SandboxResolver` loads Egress credentials by ID and selects `credential_field`. Legacy JSON names may deserialize for rollback tooling but are never read by runtime builders.

- [ ] **Step 4: Run GREEN and static name-query guard**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test && cargo clippy --all-targets --all-features -- -D warnings && ! rg -n 'WHERE[^\n]*name|secret_ref|credential_ref' src/db/queries/credential.rs src/kernel/harness_input_builder.rs src/kernel/sandbox_resolver.rs`

Expected: tests and Clippy pass; the final guard returns success because no runtime name reference remains in the scoped files.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/ids.rs backend/app/joysafeter_orchestrator_rs/src/db/models.rs backend/app/joysafeter_orchestrator_rs/src/db/queries/mod.rs backend/app/joysafeter_orchestrator_rs/src/db/queries/agent.rs backend/app/joysafeter_orchestrator_rs/src/db/queries/credential.rs backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs
git commit -m "feat(orchestrator): resolve credentials by ID"
```

---

### Task 11: Add Resumable Online Backfill

**Files:**
- Create: `backend/app/joysafeter_domain/services/joysafeter_credential_reference_backfill_service.py`
- Create: `backend/scripts/backfill_credential_references.py`
- Create: `backend/tests/services/test_credential_reference_backfill.py`

**Interfaces:**
- Consumes: legacy owner snapshots, any existing semantic IDs, resolver validation, projector replacement, and `CredentialReferenceMigrationRun` checkpoints.
- Produces: `BackfillConsumerType`, `BackfillBatchResult`, `run_batch()`, `verify_all()`, resumable high-water marks, and an operator CLI with nonzero exit status for unresolved active references.

- [ ] **Step 1: Write failing backfill tests**

```python
async def test_backfill_is_idempotent(backfill, legacy_agent, llm_secret) -> None:
    first = await backfill.run_batch(consumer_type=BackfillConsumerType.AGENT, batch_size=100)
    second = await backfill.run_batch(consumer_type=BackfillConsumerType.AGENT, batch_size=100)
    assert first.backfilled_count == 1
    assert second.backfilled_count == 0
    assert second.validated_existing_count == 1
    assert await agent_binding_ids(legacy_agent.id) == [llm_secret.id]


async def test_backfill_records_unresolved_without_advancing_success(backfill, broken_trigger) -> None:
    result = await backfill.run_batch(consumer_type=BackfillConsumerType.TRIGGER, batch_size=100)
    assert result.unresolved_count == 1
    assert result.status is BackfillStatus.NEEDS_REPAIR
    assert result.failures[0].owner_id == str(broken_trigger.id)
    assert "value" not in result.failures[0].model_dump()
```

Add Agent, Trigger, Environment direct, Environment Egress, deleted credential, cross-project collision, ambiguous historical name, mixed migrated/legacy, resume-after-interruption, and deterministic Binding rerun cases.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/services/test_credential_reference_backfill.py -q`

Expected: service import fails.

- [ ] **Step 3: Implement batch service and CLI**

```python
class BackfillConsumerType(StrEnum):
    AGENT = "agent"
    TRIGGER = "trigger"
    ENVIRONMENT = "environment"


@dataclass(frozen=True)
class BackfillBatchResult:
    run_id: CredentialMigrationRunId
    consumer_type: BackfillConsumerType
    scanned_count: int
    backfilled_count: int
    validated_existing_count: int
    unresolved_count: int
    conflict_count: int
    high_water_mark: uuid.UUID | None
    status: BackfillStatus


async def run_batch(
    self,
    *,
    consumer_type: BackfillConsumerType,
    batch_size: int,
    resume_run_id: CredentialMigrationRunId | None = None,
) -> BackfillBatchResult:
    run = await self._load_or_create_run(consumer_type, resume_run_id)
    owners = await self._load_batch_after(run.high_water_mark, consumer_type, batch_size)
    return await self._process_and_checkpoint(run, owners)
```

Each batch orders owners by UUID, selects strictly after the stored high-water mark, migrates one owner per transaction, validates existing IDs instead of overwriting them, and records sanitized failure metadata. CLI contract:

```text
uv run python scripts/backfill_credential_references.py run --consumer agent --batch-size 200
uv run python scripts/backfill_credential_references.py resume --run-id credmig_018f47f0-7b5b-7f82-8c62-2c34938b38d9
uv run python scripts/backfill_credential_references.py verify --format json
```

`verify` exits `0` only when every active owner is resolved and projected; `run`/`resume` exit `2` when repair is required and `1` on operational failure.

- [ ] **Step 4: Run GREEN tests and CLI help**

Run: `cd backend && uv run pytest tests/services/test_credential_reference_backfill.py -q && uv run python scripts/backfill_credential_references.py --help`

Expected: all backfill tests pass and help lists `run`, `resume`, and `verify`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_credential_reference_backfill_service.py backend/scripts/backfill_credential_references.py backend/tests/services/test_credential_reference_backfill.py
git commit -m "feat(credentials): add resumable reference backfill"
```

---

### Task 12: Add Cutover Gate and ID-Only Enforcement

**Files:**
- Create: `backend/app/joysafeter_domain/services/joysafeter_credential_cutover_service.py`
- Modify: `backend/app/joysafeter_shared/config/settings.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_reference_resolver.py`
- Modify: `backend/app/joysafeter_api/main.py`
- Modify: `deploy/.env.example`
- Modify: `deploy/docker-compose.yml`
- Modify: `deploy/k8s/orchestrator-deployment.yaml`
- Create: `backend/tests/services/test_credential_cutover_gate.py`
- Modify: `backend/tests/test_orchestrator_startup_fail_closed.py`

**Interfaces:**
- Consumes: backfill verification, projection drift verification, `CredentialReferenceMode`, and startup configuration.
- Produces: `CredentialCutoverReport`, `assert_id_only_ready()`, fail-closed Python/Rust deployment startup, and explicit rollback to `dual_read`.

- [ ] **Step 1: Write failing gate tests**

```python
async def test_id_only_gate_rejects_unresolved_active_owner(cutover, broken_agent) -> None:
    report = await cutover.inspect()
    assert report.ready is False
    assert report.unresolved_by_consumer == {"agent": 1}
    with pytest.raises(RuntimeError, match="credential ID cutover gate failed"):
        await cutover.assert_id_only_ready()


async def test_id_only_gate_accepts_zero_drift(cutover, fully_migrated_fixture) -> None:
    report = await cutover.inspect()
    assert report.ready is True
    assert report.runtime_name_fallback_count == 0
```

Add failures for missing ID, wrong project/kind, absent field, Binding mismatch, and any observed runtime fallback. Add startup tests proving `id_only` refuses readiness before serving traffic.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/services/test_credential_cutover_gate.py tests/test_orchestrator_startup_fail_closed.py -q`

Expected: cutover service is absent and startup does not enforce readiness.

- [ ] **Step 3: Implement cutover report and deployment switch**

```python
@dataclass(frozen=True)
class CredentialCutoverReport:
    ready: bool
    unresolved_by_consumer: Mapping[str, int]
    invalid_by_reason: Mapping[str, int]
    binding_projection_mismatches: int
    runtime_name_fallback_count: int


async def assert_id_only_ready(self) -> CredentialCutoverReport:
    report = await self.inspect()
    if not report.ready:
        raise RuntimeError(f"credential ID cutover gate failed: {report.safe_summary()}")
    return report
```

When `Settings.credential_reference_mode is ID_ONLY`, application startup runs the gate before readiness becomes healthy. Resolver name adaptation remains available only in API compatibility methods; all internal name-only calls raise `CREDENTIAL_ID_REQUIRED`. Set deployment examples to:

```text
JOYSAFETER_CREDENTIAL_REFERENCE_MODE=dual_read
```

The runbook cutover changes this exact value to `id_only` only after `verify` succeeds. Rollback changes only the mode back to `dual_read`; it never deletes ID or Binding data.

- [ ] **Step 4: Run GREEN tests and manifest checks**

Run: `cd backend && uv run pytest tests/services/test_credential_cutover_gate.py tests/test_orchestrator_startup_fail_closed.py -q && cd .. && bash -n deploy/deploy.sh && docker compose -f deploy/docker-compose.yml config >/dev/null`

Expected: gate tests pass, deployment shell syntax is valid, and Compose accepts the new environment variable.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_credential_cutover_service.py backend/app/joysafeter_shared/config/settings.py backend/app/joysafeter_domain/services/joysafeter_credential_reference_resolver.py backend/app/joysafeter_api/main.py deploy/.env.example deploy/docker-compose.yml deploy/k8s/orchestrator-deployment.yaml backend/tests/services/test_credential_cutover_gate.py backend/tests/test_orchestrator_startup_fail_closed.py
git commit -m "feat(credentials): enforce ID-only cutover gate"
```

---

### Task 13: Add Observability, Drift, and Concurrency Proofs

**Files:**
- Create: `backend/app/joysafeter_shared/credential_reference_observability.py`
- Modify: resolver, projector, backfill, cutover, and Secret lifecycle services from Tasks 3, 4, 11, and 12
- Create: `backend/tests/test_credential_reference_observability.py`
- Create: `backend/tests/test_credential_binding_concurrency.py`

**Interfaces:**
- Consumes: reference outcomes, projection rebuilds, lock timings, batch timings, and sanitized owner/credential identifiers.
- Produces: bounded-cardinality metrics, six structured audit event types, drift diagnostics, and PostgreSQL concurrency regressions for every required race.

- [ ] **Step 1: Write failing observability and concurrency tests**

```python
def test_audit_payload_never_contains_plaintext() -> None:
    payload = credential_reference_event(
        event_type="credential_reference.backfilled",
        project_id="project-a",
        consumer_type="agent",
        owner_id="agent_018f47f0-7b5b-7f82-8c62-2c34938b38d9",
        credential_id="secret_018f47f0-7b5b-7f82-8c62-2c34938b38d9",
        outcome="success",
    )
    assert set(payload) == {
        "event_type", "project_id", "consumer_type", "owner_id", "credential_id", "outcome"
    }


async def test_secret_delete_racing_with_agent_bind_has_one_serializable_winner(pg_sessions) -> None:
    bind_result, delete_result = await race_bind_and_soft_delete(pg_sessions)
    assert sorted([bind_result, delete_result]) in (["bound", "delete_blocked"], ["bind_rejected", "deleted"])
    assert await dangling_binding_count() == 0
```

Add Trigger/delete, Environment/delete, two owners/same credential, rebind A→B, and multi-credential reverse-order races. Assert no deadlock and exact post-transaction projection equality.

- [ ] **Step 2: Run RED tests**

Run: `cd backend && uv run pytest tests/test_credential_reference_observability.py tests/test_credential_binding_concurrency.py -q`

Expected: observability module is absent and at least one race can violate the intended invariant.

- [ ] **Step 3: Implement metrics and audit events**

```python
REFERENCE_COUNTER_NAMES = (
    "credential_references_discovered_total",
    "credential_references_backfilled_total",
    "credential_reference_failures_total",
    "credential_binding_projection_mismatches_total",
    "credential_compatibility_name_resolutions_total",
    "credential_runtime_name_fallback_total",
    "credential_id_only_resolution_failures_total",
    "credential_lock_contention_total",
    "credential_backfill_retries_total",
)

AUDIT_EVENT_TYPES = (
    "credential_reference.backfilled",
    "credential_reference.unresolved",
    "credential_reference.conflict",
    "credential_binding.rebuilt",
    "credential_reference.cutover_enabled",
    "credential_reference.rollback_enabled",
)
```

Use only `consumer_type`, `binding_purpose`, `outcome`, and `reason` as metric labels. Record owner/credential IDs only in structured audit fields, never metric labels. Add histograms for backfill batch duration and bind/delete lock wait. Ensure projector and soft delete acquire identical ascending Secret UUID locks so all six concurrency tests terminate deterministically.

- [ ] **Step 4: Run GREEN tests repeatedly**

Run: `cd backend && uv run pytest tests/test_credential_reference_observability.py -q && for i in {1..10}; do uv run pytest tests/test_credential_binding_concurrency.py -q || exit 1; done`

Expected: observability tests pass; ten concurrency repetitions produce no dangling reference, drift, or deadlock.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/credential_reference_observability.py backend/app/joysafeter_domain/services/joysafeter_credential_reference_resolver.py backend/app/joysafeter_domain/services/joysafeter_credential_binding_projector.py backend/app/joysafeter_domain/services/joysafeter_credential_reference_backfill_service.py backend/app/joysafeter_domain/services/joysafeter_credential_cutover_service.py backend/app/joysafeter_domain/services/joysafeter_secret_service.py backend/tests/test_credential_reference_observability.py backend/tests/test_credential_binding_concurrency.py
git commit -m "test(credentials): prove migration integrity under races"
```

---

### Task 14: Verify Full Cutover and Write Operator Runbook

**Files:**
- Create: `docs/runbooks/secret-reference-id-migration.md`
- Modify: `docs/superpowers/specs/2026-08-10-secret-reference-id-migration-design.md` only if implementation review discovers an explicit contract correction
- Modify: this plan only to check completed task boxes during execution

**Interfaces:**
- Consumes: all semantic APIs, Binding projection, backfill CLI, cutover gate, frontend, Rust runtime, migration, deployment, and rollback behavior.
- Produces: full verification evidence and an exact operator sequence for expand, compatibility deploy, backfill, repair, gate, cutover, rollback, and next-release contract cleanup.

- [ ] **Step 1: Write the runbook with exact commands and stop conditions**

The runbook must include this ordered sequence:

```text
1. Apply Alembic revision 20260810_000003 while all services remain in dual_read.
2. Deploy Python, frontend, and Rust compatibility binaries with CREDENTIAL_REFERENCE_MODE=dual_read.
3. Run backfill for agent, trigger, and environment until every run reaches completed.
4. Run verify and stop if unresolved, conflict, invalid, drift, or runtime fallback counts are nonzero.
5. Change Python and Rust deployments to CREDENTIAL_REFERENCE_MODE=id_only.
6. Confirm readiness, ID-only resolution metrics, Binding drift, and representative Agent/Trigger/Environment executions.
7. Roll back by restoring dual_read only; retain ID columns and Binding rows.
8. In the following contract release, remove legacy columns/JSON names/adapters after the rollback window closes.
```

Include SQL read-only diagnostics for counts by consumer/purpose and orphan detection, expected CLI exit codes, metric names, audit events, rollback decision criteria, and an explicit warning never to print the encrypted `data` column.

- [ ] **Step 2: Run focused migration verification**

Run:

```bash
cd backend
uv run pytest \
  tests/test_credential_reference_mode.py \
  tests/test_models/test_secret_reference_id_migration.py \
  tests/services/test_credential_reference_resolver.py \
  tests/services/test_credential_binding_projector.py \
  tests/services/test_credential_reference_backfill.py \
  tests/services/test_credential_cutover_gate.py \
  tests/test_credential_binding_concurrency.py \
  tests/test_credential_reference_observability.py -q
```

Expected: all migration-focused tests pass.

- [ ] **Step 3: Run full backend, frontend, Rust, and migration suites**

Run:

```bash
cd backend
uv run pytest -q
uv run ruff check app tests scripts
uv run pyright app

cd ../frontend
bun run test
bun run type-check
bun run lint

cd ../backend/app/joysafeter_orchestrator_rs
cargo test
cargo clippy --all-targets --all-features -- -D warnings

cd ../../../
git diff --check
```

Expected: all suites and static checks pass; unrelated pre-existing warnings are documented without changing their code.

- [ ] **Step 4: Run architecture guards and deployment validation**

Run:

```bash
! rg -n 'get_secret_by_name|secret_ref|credential_ref' \
  backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs \
  backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs \
  backend/app/joysafeter_orchestrator_rs/src/db/queries/credential.rs

rg -n 'model_connection_id|service_credential_id|service_credential_ids|credential_field' \
  backend/app frontend backend/app/joysafeter_orchestrator_rs/src

bash -n deploy/deploy.sh
docker compose -f deploy/docker-compose.yml config >/dev/null
kubectl apply --dry-run=client -f deploy/k8s/orchestrator-deployment.yaml >/dev/null
```

Expected: the no-name guard passes, semantic fields are present across all three runtimes, and deployment definitions validate.

- [ ] **Step 5: Commit verification documentation**

```bash
git add docs/runbooks/secret-reference-id-migration.md docs/superpowers/specs/2026-08-10-secret-reference-id-migration-design.md docs/superpowers/plans/2026-08-10-secret-reference-id-migration.md
git commit -m "docs: add credential ID migration runbook"
```

---

## Completion Gate

Do not mark the migration complete until all of these statements are backed by test or command output:

- Every active Agent, Trigger, and Environment owner has valid semantic credential IDs.
- Binding rows exactly match owner semantic configuration and contain no credential field values.
- Python and Rust runtime paths perform no credential name lookup in `id_only`.
- Secret rename requires no consumer update and does not change any Binding row.
- Bind/delete races cannot create a dangling reference.
- Backfill verification reports zero unresolved, conflict, invalid, and projection-drift counts.
- New frontend payloads use IDs while visible selector labels remain names.
- Compatibility clients can still submit names without persisting name identity into domain/runtime paths.
- Rollback to `dual_read` is tested and retains ID/Binding data.
- The contract-release deletion of legacy fields remains a separate, explicitly scheduled next-release change.

# Strict Entity ID Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all pre-release bare UUID string compatibility while retaining explicit native-UUID adapters only at PostgreSQL, Redis, runner, telemetry, and other documented physical boundaries.

**Architecture:** Public strings are parsed only by type-specific `from_public`/frontend parser functions and always require the canonical entity prefix. Domain code carries concrete typed IDs; native UUID conversion uses named `from_uuid`/`as_uuid` adapters. Architecture tests prevent generic constructors, prefix stripping, dual-format queries, and implicit Rust UUID conversions from returning.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, FastAPI, TypeScript 5, React 19, Vitest, Rust 2021, serde, sqlx, pytest.

## Global Constraints

- Public API paths, queries, request JSON, response JSON, frontend state, and persisted JSON/JSONB use canonical typed prefixed strings.
- Bare UUID strings and wrong entity prefixes are rejected at public boundaries.
- Python domain code uses concrete `EntityId` subtypes; Rust domain code uses concrete typed ID wrappers.
- PostgreSQL UUID columns and explicitly documented Redis, protobuf, runner, telemetry, and third-party physical contracts may use native/bare UUIDs through named adapters only.
- No data migration or compatibility read path is required; development and test databases may be rebuilt.
- Do not introduce broader regex replacement or normalization. Classify each occurrence by boundary.
- Do not create commits unless the user explicitly requests them.

---

### Task 1: Make Python ID construction semantic

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py:18`
- Modify: `backend/tests/test_entity_ids.py:22`
- Modify: `backend/tests/test_typed_id_architecture.py:120`

**Interfaces:**
- Consumes: Existing concrete `EntityId` subclasses and `EntityIdType` SQLAlchemy adapter.
- Produces: `EntityId.from_public(str)`, `EntityId.from_uuid(uuid.UUID)`, `EntityId.new()`, and `as_uuid(EntityId | uuid.UUID)` as the only conversion interfaces.

- [ ] **Step 1: Replace compatibility tests with strict-construction tests**

```python
def test_direct_constructor_rejects_all_strings():
    value = uuid.uuid4()
    with pytest.raises(TypeError, match="cannot build AgentId from str"):
        AgentId(str(value))
    with pytest.raises(TypeError, match="cannot build AgentId from str"):
        AgentId(f"agent_{value}")


def test_named_factories_separate_public_and_physical_values():
    value = uuid.uuid4()
    assert AgentId.from_uuid(value).uuid == value
    assert AgentId.from_public(f"agent_{value}").uuid == value
    with pytest.raises(ValueError, match="expected agent_ prefix"):
        AgentId.from_public(str(value))
```

Add an `EntityIdType.process_bind_param` assertion that a bare UUID string raises `TypeError`, while a native `uuid.UUID` and `AgentId` bind to the native UUID.

- [ ] **Step 2: Run the focused tests and confirm the old constructor still fails the new contract**

Run: `cd backend && uv run pytest tests/test_entity_ids.py -q`

Expected: the two direct-string assertions fail because `EntityId.__init__` still parses strings.

- [ ] **Step 3: Restrict the Python value object implementation**

Implement the constructor/factory split in `ids.py`:

```python
def __init__(self, value: uuid.UUID | "EntityId") -> None:
    self._uuid = self._coerce(value)

@classmethod
def _coerce(cls, value: Any) -> uuid.UUID:
    if isinstance(value, EntityId):
        if type(value) is not cls:
            raise TypeError(f"cannot build {cls.__name__} from {type(value).__name__}")
        return value.uuid
    if isinstance(value, uuid.UUID):
        return value
    raise TypeError(f"cannot build {cls.__name__} from {type(value).__name__}")

@classmethod
def from_public(cls, value: str) -> Self:
    if not isinstance(value, str) or not value.startswith(cls.prefix):
        raise ValueError(f"expected {cls.prefix} prefix")
    return cls.from_uuid(uuid.UUID(value[len(cls.prefix):]))
```

Keep Pydantic's string branch routed through `from_public`; keep native UUID hydration routed through `from_uuid`. Make `EntityIdType.process_bind_param` explicitly branch on the correct ID class or `uuid.UUID` and reject strings instead of calling a generic constructor fallback.

- [ ] **Step 4: Add an architecture guard against direct ID construction outside the ID module**

In `test_typed_id_architecture.py`, scan `backend/app/**/*.py` excluding `joysafeter_shared/ids.py` for direct calls matching the concrete ID class names followed by `(`. The expected list is empty; application code must call `.from_public`, `.from_uuid`, or `.new`.

- [ ] **Step 5: Run the Python ID unit and architecture tests**

Run: `cd backend && uv run pytest tests/test_entity_ids.py tests/test_typed_id_architecture.py -q`

Expected: PASS.

### Task 2: Remove Python public-boundary compatibility call sites

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/files.py:42`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py:48`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py:87`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_session.py:220`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_file.py:25`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_service.py:1011`
- Modify: `backend/tests/test_id_helper_error_contract.py:95`
- Modify: `backend/tests/test_entity_ids.py:156`
- Modify: `backend/tests/test_environment_lifecycle_active_sessions.py:380`

**Interfaces:**
- Consumes: Strict factories from Task 1.
- Produces: Canonical session scope parsing, typed session agent aliases, strict environment reference classification, and typed internal event batches.

- [ ] **Step 1: Add failing public-boundary regression tests**

Add these cases:

```python
def test_file_scope_rejects_bare_session_uuid():
    with pytest.raises(AppError):
        _parse_session_scope(str(uuid.uuid4()))


def test_create_session_agent_alias_rejects_bare_uuid_string():
    with pytest.raises(ValidationError):
        CreateSessionRequest(agent=str(uuid.uuid4()))


def test_create_session_agent_alias_accepts_canonical_agent_id():
    agent_id = AgentId.new()
    request = CreateSessionRequest(agent=str(agent_id))
    assert request.agent is None
    assert request.agent_id == agent_id
```

Add an environment-reference test proving a canonical `env_<uuid>` is accepted, an environment name remains valid, and a bare UUID is rejected as `ENVIRONMENT_ID_INVALID` rather than silently treated as a name.

- [ ] **Step 2: Run the focused API/schema tests and confirm failures**

Run: `cd backend && uv run pytest tests/test_id_helper_error_contract.py tests/test_entity_ids.py tests/test_environment_lifecycle_active_sessions.py -q`

Expected: bare file scope or environment UUID behavior fails the new assertions, and direct constructors fail after Task 1.

- [ ] **Step 3: Replace each ambiguous constructor with its semantic factory**

Apply these exact decisions:

- `_parse_session_scope`: use `SessionId.from_public(scope_id)` and change the query description to `sess_<uuid>` only.
- `_environment_conflict_error`: parse the captured task reference with `TaskId.from_public(task_id)` because the domain error message contains `str(TaskId)`.
- `CreateSessionRequest.agent`: type the surviving field as `AgentRef | None`; keep the `mode="before"` alias adapter that moves a string into `agent_id`, allowing Pydantic's `AgentId` validator to enforce the prefix.
- `create_session`: remove the unreachable string-constructor branch and handle only `AgentRef`, `agent_id`, or `agent_name`.
- `FileResponse.from_model`: assign `obj.session_id` directly because the ORM column already hydrates `SessionId`; update tests to use a typed model fixture instead of a raw UUID.
- `batch_insert_session_events`: accept `SessionId` as the internal event dictionary value; if a native UUID is genuinely supplied by a database adapter, convert only in a visibly named `SessionId.from_uuid` branch and reject strings.

- [ ] **Step 4: Make polymorphic environment references explicit without optional-prefix parsing**

Implement classification with native UUID parsing rather than an optional-prefix regex:

```python
if ref.startswith(EnvironmentId.prefix):
    try:
        return str(EnvironmentId.from_public(ref))
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(code="ENVIRONMENT_ID_INVALID", ...) from exc
try:
    uuid.UUID(ref)
except ValueError:
    return ref
raise InvalidRequestError(code="ENVIRONMENT_ID_INVALID", ...)
```

This preserves names while making a UUID-shaped unprefixed value an invalid entity reference.

- [ ] **Step 5: Run focused Python API and service tests**

Run: `cd backend && uv run pytest tests/test_id_helper_error_contract.py tests/test_entity_ids.py tests/test_environment_lifecycle_active_sessions.py tests/test_session_resource_error_contract.py -q`

Expected: PASS.

### Task 3: Delete frontend prefix-stripping compatibility

**Files:**
- Modify: `frontend/types/entity-id.ts:1`
- Modify: `frontend/types/entity-id.test.ts:1`
- Modify: `frontend/lib/managed/api-paths.ts:1`
- Modify: `frontend/lib/managed/api-paths.test.ts:1`
- Modify: `frontend/lib/managed/id.ts:1`
- Modify: `frontend/app/managed/sessions/components/create-session-dialog.tsx:273`
- Modify: `frontend/app/managed/sessions/[sessionId]/page.tsx:996`
- Modify: `frontend/app/managed/skills/new-ai/page.tsx:427`
- Modify: `frontend/app/managed/quickstart/page.tsx:1319`
- Modify: `frontend/types/entity-id-architecture.test.ts:1`

**Interfaces:**
- Consumes: `ENTITY_ID_PREFIXES`, `isEntityId`, concrete branded ID types.
- Produces: `AnyEntityId`, `parseAnyEntityId(value)`, and display-only `shortEntityId(id, kind, length)`; API path helpers accept canonical entity IDs without normalization.

- [ ] **Step 1: Write failing frontend tests for strict paths and exact equality**

Replace the legacy-normalization test with:

```typescript
it('rejects bare and malformed resource ids', () => {
  expect(() => apiResourceId(UUID)).toThrow(TypeError)
  expect(() => apiResourceId(`task_agent_${UUID}`)).toThrow(TypeError)
})
```

Add an entity-ID utility test proving `parseAnyEntityId` accepts every registered canonical prefix and rejects bare UUIDs and stacked prefixes. Add an architecture assertion that no production frontend file imports or calls `stripIdPrefix` or `withIdPrefix`.

- [ ] **Step 2: Run the focused Vitest files and confirm the fallback still violates the contract**

Run: `cd frontend && bun test types/entity-id.test.ts lib/managed/api-paths.test.ts types/entity-id-architecture.test.ts`

Expected: the strict API-path test fails because `apiResourceId` still strips prefixes.

- [ ] **Step 3: Introduce strict all-entity parsing and display helpers**

In `types/entity-id.ts`, export an `AnyEntityId` union and implement `parseAnyEntityId` by iterating the existing `EntityKind` registry and returning only when `isEntityId` succeeds. Do not add a second regex registry.

Replace `lib/managed/id.ts` with display-only helpers that require a validated `AnyEntityId` and a matching kind:

```typescript
export function entityIdUuid<Kind extends EntityKind>(
  id: EntityId<(typeof ENTITY_ID_PREFIXES)[Kind]>,
  kind: Kind,
): string {
  const parsed = parseEntityId(id, kind)
  return parsed.slice(ENTITY_ID_PREFIXES[kind].length)
}
```

`shortEntityId` may format `${prefix}${uuid.slice(0, length)}` for display, but it must never be used for routing, equality, cache keys, or request bodies.

- [ ] **Step 4: Make API paths preserve only validated canonical IDs**

Change `apiResourceId` to return `parseAnyEntityId(value)` and remove `stripIdPrefix`. Keep collection names and non-ID child segments handled separately by `cleanSegment`.

Update call sites:

- Environment default selection compares `env.id === ref` only.
- Session heading uses `session.id` directly; short labels call the typed display helper with the known entity kind.
- Skill authoring routes with `selected=${encodeURIComponent(skillId)}` and does not remove `skill_`.
- Quickstart display uses validated typed IDs instead of constructing a prefix around an arbitrary string.

- [ ] **Step 5: Run frontend unit, architecture, and type checks**

Run: `cd frontend && bun test types/entity-id.test.ts lib/managed/api-paths.test.ts types/entity-id-architecture.test.ts app/managed/sessions/components/create-session-dialog.test.tsx hooks/managed/use-quickstart-chat.test.tsx`

Run: `cd frontend && bun run type-check`

Expected: PASS.

### Task 3A: Type storage resource identities end to end

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_storage_mount.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_storage_mount.py`
- Modify: `backend/app/joysafeter_api/api/v1/storage_volumes.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_storage_mount_service.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_session.py`
- Modify: `backend/tests/test_entity_ids.py`
- Modify: `backend/tests/test_typed_id_architecture.py`
- Modify: storage-volume API/service contract tests selected by the implementer
- Modify: `frontend/types/entity-id.ts`
- Modify: `frontend/types/entity-id.test.ts`
- Modify: `frontend/types/managed.ts`
- Modify: `frontend/lib/managed/storage-mount-response-parsers.ts`
- Modify: `frontend/components/managed/storage-volumes/storage-volumes-page.tsx`
- Modify: relevant storage response/parser tests

**Interfaces:**
- Consumes: Strict Python/TypeScript entity-ID factories from Tasks 1 and 3.
- Produces: `StorageVolumeId` (`vol_`), `StorageGrantId` (`stgrant_`), and `StorageMountAuditId` (`staudit_`); session storage-mount rows reuse `SessionResourceId` (`sesrsc_`).

- [ ] **Step 1: Add failing backend and frontend storage-ID contract tests**

Assert canonical serialization and bare/cross-prefix rejection for the three new ID classes. Assert Storage Volume responses, grant responses, Session storage-mount responses, audit responses, route parameters, audit `volume_id`, and audit cursors use their typed IDs.

- [ ] **Step 2: Run focused tests and confirm current bare UUID contracts fail**

Run the selected backend storage contract tests plus `tests/test_entity_ids.py` and `tests/test_typed_id_architecture.py`; run frontend entity-ID and storage parser tests.

- [ ] **Step 3: Type Python storage models, schemas, routes, and services**

Use `EntityIdType` for UUID columns without changing physical schema:

- `JoySafeterStorageVolume.id` → `StorageVolumeId`.
- Project and organization grant `id` → shared `StorageGrantId`; `volume_id` → `StorageVolumeId`.
- `JoySafeterSessionStorageMount.id` → `SessionResourceId`; `volume_id` → `StorageVolumeId`.
- `JoySafeterStorageMountAudit.id` → `StorageMountAuditId`; optional `volume_id` → `StorageVolumeId`.

Replace public `uuid.UUID` route/query/schema annotations with those types, remove manual UUID serializers, and keep native UUID conversion only inside `EntityIdType`/SQL boundaries. Do not add an Alembic migration because column types remain UUID and databases are rebuilt.

- [ ] **Step 4: Type frontend storage responses and paths**

Add the new kinds to the existing entity-ID registry, type `StorageVolume`, grants, Session storage mounts, and audit records, parse every response ID at ingress, and keep canonical IDs unchanged in storage-volume routes and audit filters.

- [ ] **Step 5: Run backend/frontend focused verification and type-check**

Run the selected backend storage/API tests, frontend storage/parser tests, frontend type-check, and architecture guards. Expected: PASS.

### Task 4: Make Rust UUID degradation explicit

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/ids.rs:1`

**Interfaces:**
- Consumes: Existing `from_public`, `from_uuid`, `as_uuid`, `to_public` methods and sqlx transparent newtypes.
- Produces: Public-prefixed serde representation and no implicit `From<Uuid>`/`From<EntityId> for Uuid` conversion.

- [ ] **Step 1: Add failing Rust tests for serde and explicit conversion**

Change the storage test into two boundary tests:

```rust
#[test]
fn serde_uses_the_public_prefixed_representation() {
    let id = AgentId::from_uuid(Uuid::now_v7());
    assert_eq!(serde_json::to_value(id).unwrap(), id.to_public());
    assert_eq!(serde_json::from_value::<AgentId>(serde_json::json!(id.to_public())).unwrap(), id);
    assert!(serde_json::from_value::<AgentId>(serde_json::json!(id.as_uuid().to_string())).is_err());
}

#[test]
fn physical_boundary_requires_as_uuid() {
    let uuid = Uuid::now_v7();
    assert_eq!(AgentId::from_uuid(uuid).as_uuid(), uuid);
}
```

- [ ] **Step 2: Run the Rust ID tests and confirm serde is still bare**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test ids::tests`

Expected: `serde_uses_the_public_prefixed_representation` fails because `#[serde(transparent)]` serializes the inner UUID.

- [ ] **Step 3: Implement public serde and remove implicit UUID conversions**

Remove `Serialize`, `Deserialize`, and `#[serde(transparent)]` from the derive list. Implement `Serialize` using `serializer.serialize_str(&self.to_public())`; implement `Deserialize` by reading a string and calling `from_public`. Remove both `From<Uuid> for Id` and `From<Id> for Uuid`; callers must name `from_uuid` or `as_uuid`.

Keep `#[repr(transparent)]` and `#[sqlx(transparent)]` so SQL UUID columns remain physical UUID boundaries.

- [ ] **Step 4: Run Rust unit tests and compile the orchestrator**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test ids::tests`

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test --no-run`

Expected: PASS; any compile error identifies an implicit UUID conversion that must be replaced with `from_uuid` or `as_uuid` at its classified boundary.

### Task 5: Lock the boundary inventory and remove stale guidance

**Files:**
- Modify: `backend/tests/test_typed_id_architecture.py:1`
- Modify: `frontend/types/entity-id-architecture.test.ts:1`
- Modify: `docs/ARCHITECTURE.md:475`
- Modify: `docs/api/openapi.md:75`
- Modify: `docs/superpowers/specs/2026-08-06-typed-entity-id-value-objects-design.md:1`
- Modify: `docs/superpowers/plans/2026-08-06-typed-entity-ids-completion-audit.md:1`
- Modify: `docs/superpowers/specs/2026-08-07-strict-entity-id-boundaries-design.md:1`

**Interfaces:**
- Consumes: Strict Python, frontend, and Rust behavior from Tasks 1–4.
- Produces: A stable architecture guard and an authoritative retained-physical-boundary inventory.

- [ ] **Step 1: Add exact architecture guards instead of a normalization regex**

Backend guard requirements:

- No direct concrete `Id(...)` construction outside `joysafeter_shared/ids.py`.
- No entity-prefix `removeprefix` calls in application code.
- No public parameter descriptions advertising bare UUIDs.
- No dual prefixed/bare JSONB containment candidates.

Frontend guard requirements:

- No `stripIdPrefix` or `withIdPrefix` production imports/calls.
- `apiResourceId` must call `parseAnyEntityId` and must not call `.replace` or prefix-removal helpers.
- Equality checks use branded IDs directly.

Keep physical adapters on an explicit reviewed list rather than attempting to ban every `.uuid`, `.as_uuid()`, or native UUID parse globally.

- [ ] **Step 2: Update architecture documentation and superseded records**

Document these retained physical categories in `ARCHITECTURE.md`: SQL UUID bind/result, advisory locks, Redis queue/channel names and payloads, runner/protobuf fields, OpenTelemetry identities, object-storage keys, and third-party UUID contracts. Remove the statement that legacy bare Vault JSONB rows remain readable.

Mark the 2026-08-06 design and completion audit as superseded by the 2026-08-07 strict-boundary design wherever they describe temporary bare-string compatibility. Do not rewrite unrelated historical implementation detail.

- [ ] **Step 3: Run the repository audit searches**

Run:

```bash
rg -n -S "stripIdPrefix|withIdPrefix|legacy normalization|sess_xxx or bare UUID|accept.*bare UUID|tolerat.*bare" backend frontend docs --glob '!frontend/node_modules/**'
rg -n -P "\\b(?:AgentId|SessionId|TaskId|EnvironmentId|SecretId|TriggerId|MemoryStoreId|MemoryId|MemoryVersionId|SandboxId|VaultId|CredentialId|SkillId|SkillFileId|SkillSecurityScanId|SkillVersionId|SkillVersionFileId|SkillUsageId|EventId|FileId|SessionResourceId)\\(" backend/app --glob '*.py' --glob '!joysafeter_shared/ids.py'
```

Expected: no active compatibility implementation remains. Matches in the strict design or explicitly superseded historical documents are explanatory only.

- [ ] **Step 4: Run full targeted verification**

Run: `cd backend && uv run pytest tests/test_entity_ids.py tests/test_typed_id_architecture.py tests/test_id_helper_error_contract.py tests/test_environment_lifecycle_active_sessions.py tests/test_session_resource_error_contract.py tests/services/test_vault_reference_refs.py tests/services/test_session_skill_usage_api.py -q`

Run: `cd frontend && bun test types/entity-id.test.ts lib/managed/api-paths.test.ts types/entity-id-architecture.test.ts app/managed/sessions/components/create-session-dialog.test.tsx hooks/managed/use-quickstart-chat.test.tsx`

Run: `cd frontend && bun run type-check`

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test ids::tests && cargo test --no-run`

Expected: all commands PASS.

- [ ] **Step 5: Review the final diff and retained-boundary list**

Run: `git diff --check && git status --short`

Confirm the final summary lists removed compatibility points separately from retained physical adapters and that no database migration was added.

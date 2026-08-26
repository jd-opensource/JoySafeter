# Typed-ID Serialization Boundary Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every JoySafeter public and persisted JSON boundary emit canonical prefixed entity IDs without endpoint-local bridges, permissive fallback serializers, or obsolete compatibility routes.

**Architecture:** Concrete `EntityId` values remain intact through persistence, domain, and application layers. Typed Pydantic DTOs own REST serialization, while a strict allowlisted normalizer owns the few intentionally schema-less error, audit, WebSocket, and event boundaries. Architecture tests make missing response models and reintroduced serialization bridges fail closed.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, pytest, TypeScript, React, Vitest, Bun.

**Spec:** `docs/superpowers/specs/2026-08-25-typed-id-serialization-boundary-design.md`

## Global Constraints

- Preserve all unrelated uncommitted changes in the current working tree.
- Do not modify `.deps/SkillSpector`.
- Run backend pytest commands from `backend/`.
- Do not add bare-UUID, wrong-prefix, or dual-read compatibility behavior.
- Do not use endpoint-local `str(id)`, `default=str`, or JSON-mode DTO dumps as the REST solution.
- Do not commit or create branches unless the user explicitly requests it.
- Public entity IDs remain strict prefixed strings; PostgreSQL remains native UUID.
- Targeted tests run before broader suites.

---

### Task 1: Prove the REST Serialization Failure

**Files:**
- Modify: `backend/tests/test_tenant_auth_rest_id_contract.py`
- Create: `backend/tests/test_rest_response_serialization_contract.py`

**Interfaces:**
- Consumes: `EntityId` Pydantic integration and FastAPI route registration.
- Produces: ASGI-level regression tests and reusable assertions for canonical public IDs.

- [ ] **Step 1: Add a raw-dictionary regression test**

Add a small FastAPI route that returns a raw dictionary containing
`UserId.new()`. Assert that the current behavior is `{}` so the original causal
mechanism is captured before production code changes.

```python
def test_raw_entity_id_dictionary_loses_transport_type_information() -> None:
    user_id = UserId.new()
    app = FastAPI()

    @app.get("/raw")
    async def raw():
        return {"id": user_id}

    assert TestClient(app).get("/raw").json() == {"id": {}}
```

- [ ] **Step 2: Add typed-model control coverage**

Add a sibling route returning a Pydantic model whose `id` field is `UserId`.
Assert the response is `str(user_id)`.

```python
class UserPayload(BaseModel):
    id: UserId

@app.get("/typed")
async def typed() -> UserPayload:
    return UserPayload(id=user_id)
```

- [ ] **Step 3: Add `/auth/me` ASGI regression coverage**

Build a FastAPI test app with the auth router and dependency overrides. Supply
a fake async database result sequence and project service so the HTTP request
reaches `get_me` without a real token or leaked credentials. Assert canonical
values for all current and list user/organization/project ID fields. Also
recursively assert that no dictionary value equals `{}`.

- [ ] **Step 4: Add login and registration response regressions**

Override or monkeypatch `AuthService.login` and `AuthService.register` to return
the current typed-ID-bearing result. Call the real routes through `TestClient`
and assert `data.user.id` is the canonical `user_<uuid>` string and cookie
headers remain present where applicable.

- [ ] **Step 5: Run the tests and verify intended failures**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_rest_response_serialization_contract.py \
  tests/test_tenant_auth_rest_id_contract.py
```

Expected before implementation: the typed-model control passes; `/auth/me`,
login, and registration ASGI assertions fail because IDs are `{}`.

---

### Task 2: Type Authentication Application Results

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_auth_service.py`
- Modify: `backend/app/joysafeter_identity_federation/infrastructure/session_gateway.py`
- Modify: `backend/tests/test_auth_service_login_tokens.py`
- Modify: `backend/tests/test_identity_federation_session_gateway.py`

**Interfaces:**
- Produces: immutable `IssuedLoginTokens` with typed user and token-expiry fields.
- Consumes: `AuthUser`, token generation, and identity-federation `IssuedAuthSession`.

- [ ] **Step 1: Add failing service-result tests**

Assert `register`, `login`, and `issue_login_tokens` return an immutable typed
result instead of a JSON dictionary. The result exposes:

```python
@dataclass(frozen=True, slots=True)
class IssuedLoginTokens:
    user: AuthUser
    access_token: str
    refresh_token: str
    csrf_token: str
    token_type: str
    access_expires_at: datetime
    refresh_expires_at: datetime

    @property
    def expires_in(self) -> int: ...
```

Assert the `user.id` value remains `UserId`, not `str`.

- [ ] **Step 2: Replace `_build_jwt_login_response`**

Delete `_build_jwt_login_response`. Make token issuance construct
`IssuedLoginTokens`; update register/login/refresh-related internal callers
without converting IDs.

- [ ] **Step 3: Update the identity-federation gateway**

Read attributes from `IssuedLoginTokens` rather than dictionary keys and
continue producing the existing identity-federation `IssuedAuthSession`
contract.

- [ ] **Step 4: Run focused service tests**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_auth_service_login_tokens.py \
  tests/test_identity_federation_session_gateway.py
```

---

### Task 3: Close Auth and Tenant REST DTOs

**Files:**
- Create: `backend/app/joysafeter_api/api/v1/tenant_auth_schemas.py`
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/app/joysafeter_api/api/v1/organizations.py`
- Modify: `backend/app/joysafeter_shared/common/response.py`
- Modify: `backend/tests/test_rest_response_serialization_contract.py`
- Modify: `backend/tests/test_organization_member_error_contract.py`
- Modify: `backend/tests/test_managed_auth_context_contract.py`
- Modify: `backend/tests/test_me_capability.py`

**Interfaces:**
- Consumes: `IssuedLoginTokens` from Task 2.
- Produces: typed public auth, organization, project-context, and ownership-transfer response models.

- [ ] **Step 1: Define transport-owned nested DTOs**

Create `AuthUserSummary`, `OrganizationContextResponse`,
`ProjectContextResponse`, `ActiveProjectContextResponse`, `AuthMeResponse`,
typed login data, organization create/detail/update responses, and
ownership-transfer response. Every known ID field uses its concrete ID type.

- [ ] **Step 2: Convert auth helpers to return DTOs**

Replace `_project_context_payload` with `_project_context_response` returning
`ProjectContextResponse`. Replace `_active_project_payload` with
`_active_project_response` returning `ActiveProjectContextResponse`.

- [ ] **Step 3: Convert `/auth/me`**

Annotate `get_me` as `-> AuthMeResponse` and construct the complete model.
Preserve accessible-project filtering and active archived-project behavior.

- [ ] **Step 4: Convert login and registration envelopes**

Map `IssuedLoginTokens` to typed API DTOs. Update `_set_auth_cookies` to accept
the typed result. Return typed `ApiResponse[T]` instances instead of
`success_response()` dictionaries.

- [ ] **Step 5: Convert organization CRUD and transfer responses**

Return concrete DTO instances from create, get, update, and transfer routes.
Preserve optional fields and status codes exactly.

- [ ] **Step 6: Remove duplicate organization compatibility surface**

After confirming no supported caller uses `/api/v1/auth/organizations`, delete
the duplicate route, duplicate request/response models, and imports required
only by that route. Do not add a redirect or alias.

- [ ] **Step 7: Remove obsolete response helpers when unused**

If `success_response()` and `paginated_response()` have no production callers,
delete them. Retain `ApiResponse` and `error_response` while used.

- [ ] **Step 8: Run focused auth and organization tests**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_rest_response_serialization_contract.py \
  tests/test_tenant_auth_rest_id_contract.py \
  tests/test_organization_member_error_contract.py \
  tests/test_managed_auth_context_contract.py \
  tests/test_me_capability.py \
  tests/test_auth_service_login_tokens.py \
  tests/test_identity_federation_session_gateway.py
```

---

### Task 4: Make Pagination Cursor IDs Generic

**Files:**
- Modify: `backend/app/joysafeter_domain/schemas/base.py`
- Modify: `backend/app/joysafeter_api/api/v1/agents.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/app/joysafeter_api/api/v1/files.py`
- Modify: `backend/app/joysafeter_api/api/v1/memory_stores.py`
- Modify: `backend/app/joysafeter_api/api/v1/sandboxes.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/app/joysafeter_api/api/v1/skills.py`
- Modify: `backend/app/joysafeter_api/api/v1/tasks.py`
- Modify: `backend/app/joysafeter_api/api/v1/triggers.py`
- Modify: affected backend pagination tests

**Interfaces:**
- Produces: `CursorPaginatedResponse[ItemT, CursorIdT]`.
- Consumes: the concrete ID subtype associated with each response item.

- [ ] **Step 1: Add failing generic-schema tests**

Assert a page declared as `CursorPaginatedResponse[AgentResponse, AgentId]`
accepts `AgentId` cursors, emits canonical strings in JSON mode, and rejects
`ProjectId` and bare UUID strings.

- [ ] **Step 2: Generalize the shared schema**

```python
ItemT = TypeVar("ItemT")
CursorIdT = TypeVar("CursorIdT")

class CursorPaginatedResponse(BaseModel, Generic[ItemT, CursorIdT]):
    data: list[ItemT]
    has_more: bool
    first_id: CursorIdT | None = None
    last_id: CursorIdT | None = None
```

- [ ] **Step 3: Type every pagination route**

Use matching cursor types: `AgentId`, `SessionId`, `AgentVersionId`,
`EnvironmentId`, `FileId`, `MemoryStoreId`, `MemoryId`, `MemoryVersionId`,
`SandboxId`, `SkillUsageId`, `EventId`, and `TaskId`.

- [ ] **Step 4: Remove cursor string bridges**

Replace every `first_id=str(...)` and `last_id=str(...)` with the typed value.
Do not alter cursor ordering or repository query semantics.

- [ ] **Step 5: Run focused pagination suites**

```bash
cd backend
.venv/bin/pytest -q tests/test_entity_ids.py tests/test_typed_id_architecture.py
```

Also run `tests/test_agent_schema_contract.py`,
`tests/test_environment_id_boundary.py`,
`tests/test_trigger_schema_contract.py`, and
`tests/test_storage_entity_id_contract.py`.

---

### Task 5: Close Remaining REST Response Models

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/credential_groups.py`
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Modify: `backend/app/joysafeter_api/api/v1/skills.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/app/joysafeter_api/api/v1/organizations.py`
- Modify: `backend/app/joysafeter_api/api/v1/analytics.py`
- Modify: `backend/app/joysafeter_api/api/v1/skills_ai_authoring.py`
- Modify: `backend/tests/test_rest_response_serialization_contract.py`
- Modify: `backend/tests/test_typed_id_architecture.py`

**Interfaces:**
- Consumes: typed DTOs and generic cursor pages from Tasks 3 and 4.
- Produces: an explicit response contract for every body-bearing JSON route or a documented narrow allowlist.

- [ ] **Step 1: Add the response-model architecture test**

Inspect `joysafeter_router.routes` and fail when a body-bearing JSON route has
no response model. Exempt only explicit streams, downloads, redirects,
primitive-only health responses, and reviewed schema-less protocols. Every
allowlist entry includes a reason.

- [ ] **Step 2: Introduce typed list/page DTOs**

Define concrete page models for credential groups, credentials, skills, skill
files, skill versions, and other raw `{data: ...}` responses. Return DTOs
directly instead of dumping nested models.

- [ ] **Step 3: Add simple response DTOs**

Replace raw archive/delete/status dictionaries with small typed models when
they carry IDs or form a stable public contract.

- [ ] **Step 4: Remove API JSON-mode dumps**

Delete API-layer `model_dump(mode="json")` calls used only to place DTOs into
raw response dictionaries. Retain JSON-mode dumps only at a documented
persistence or external-protocol boundary.

- [ ] **Step 5: Remove analytics Python-mode ID serializers**

Update tests so `model_dump()` preserves typed IDs and
`model_dump(mode="json")` emits canonical strings. Delete field serializers
whose sole purpose was converting IDs during Python-mode dumps.

- [ ] **Step 6: Run architecture and API suites**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_rest_response_serialization_contract.py \
  tests/test_typed_id_architecture.py \
  tests/test_id_helper_error_contract.py \
  tests/test_credentials_api.py
```

---

### Task 6: Make the Success Envelope Strict

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/middleware.py`
- Modify: existing response-wrapper middleware contract tests
- Modify: `backend/tests/test_rest_response_serialization_contract.py`

**Interfaces:**
- Consumes: already JSON-safe route output.
- Produces: the existing success envelope without conversion fallback.

- [ ] **Step 1: Add middleware behavior tests**

Cover single payloads, paginated payloads, already-enveloped responses,
repeated `Set-Cookie` headers, non-JSON responses, and error responses.

- [ ] **Step 2: Remove `default=str`**

```python
wrapped_body = json.dumps(wrapped, ensure_ascii=False)
```

- [ ] **Step 3: Run middleware and cookie tests**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_rest_response_serialization_contract.py \
  tests/test_csrf_protection_contract.py
```

---

### Task 7: Introduce a Strict Schema-Less JSON Boundary

**Files:**
- Create: `backend/app/joysafeter_shared/json_boundary.py`
- Create: `backend/tests/test_json_boundary.py`
- Modify: `backend/app/joysafeter_shared/common/exceptions.py`
- Modify: `backend/app/joysafeter_api/api/v1/audit.py`
- Modify: affected error and audit tests

**Interfaces:**
- Produces: `to_json_value(value: object, *, boundary: str) -> JsonValue`.
- Consumes: explicitly schema-less error and audit values.

- [ ] **Step 1: Add strict-normalizer tests**

Test recursive support for JSON primitives, `EntityId`, `datetime`, `date`,
`Enum`, list, tuple, and string-keyed mappings. Assert non-string mapping keys
and unsupported arbitrary objects raise a boundary-specific `TypeError`
without embedding `repr(value)`.

- [ ] **Step 2: Implement the recursive normalizer**

Define a recursive `JsonValue` alias and normalize only allowlisted types.
Reject non-finite floats rather than emitting non-standard JSON.

- [ ] **Step 3: Migrate error responses**

Replace `jsonable_encoder(..., custom_encoder={EntityId: str})` with strict
normalization before constructing `JSONResponse`.

- [ ] **Step 4: Migrate audit payloads**

Normalize the audit payload once at the persistence boundary. Preserve typed
IDs before that point and keep credential redaction unchanged.

- [ ] **Step 5: Run error, audit, and security tests**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_json_boundary.py \
  tests/test_id_helper_error_contract.py \
  tests/test_credential_material_access_service.py
```

---

### Task 8: Harden WebSocket and Event JSON

**Files:**
- Modify: `backend/app/joysafeter_api/websocket/notification_manager.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/tests/test_websocket_notification_manager.py`
- Modify: `backend/tests/test_session_event_batch_id_contract.py`
- Modify: relevant SSE/event replay tests

**Interfaces:**
- Consumes: `to_json_value` from Task 7.
- Produces: canonical, fail-closed WebSocket and realtime event JSON.

- [ ] **Step 1: Add notification failure tests**

Assert nested entity IDs serialize canonically. Assert unsupported objects
cause send failure and connection cleanup rather than an unstable string.

- [ ] **Step 2: Replace WebSocket `default=str`**

Normalize messages with
`to_json_value(..., boundary="websocket_notification")` and call strict
`json.dumps`.

- [ ] **Step 3: Add realtime event normalization tests**

Cover event IDs, nested payload IDs, datetimes, enums, and unsupported values.
Verify Redis receives canonical JSON and SSE readers observe the same shape.

- [ ] **Step 4: Replace session-event `default=str`**

Normalize the complete Redis publication wrapper at the publication adapter.
Keep Redis channel naming as the documented physical UUID boundary.

- [ ] **Step 5: Audit remaining broad fallback encoders**

Retain only behavior explicitly belonging to a sanitizer contract and record
it in the architecture allowlist.

- [ ] **Step 6: Run WebSocket, event, worker, and SSE tests**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_websocket_notification_manager.py \
  tests/test_session_event_batch_id_contract.py
```

Also run:

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_sse_replay_pagination_contract.py \
  tests/test_foundation2_event_dedup.py \
  tests/test_session_message_dispatch_failure.py \
  tests/test_broadcaster_shared_subscription_contract.py
```

---

### Task 9: Update Frontend Contract Coverage

**Files:**
- Modify: `frontend/lib/managed/tenant-response-parsers.test.ts`
- Modify: `frontend/providers/project-provider.test.tsx`
- Modify: `frontend/types/entity-id-architecture.test.ts`
- Modify: frontend auth API tests if login response IDs are consumed

**Interfaces:**
- Consumes: canonical backend response fixtures from Track A.
- Produces: fail-closed frontend validation with no object, bare UUID, or prefix fallback.

- [ ] **Step 1: Add malformed `{}` regressions**

Assert auth, organization, project, membership, and pagination parsers reject
empty objects in every ID position.

- [ ] **Step 2: Add complete real-shape fixtures**

Use full `/auth/me`, organization CRUD, transfer, and pagination fixtures with
canonical IDs. Verify provider/store state is populated without conversion.

- [ ] **Step 3: Add frontend architecture scans**

Reject reintroduction of bare UUID extraction, prefix inference, compatibility
parsers, deleted helper filenames, and removed compatibility directories.

- [ ] **Step 4: Run focused frontend tests and type checking**

```bash
cd frontend
bun run test -- \
  lib/managed/tenant-response-parsers.test.ts \
  providers/project-provider.test.tsx \
  types/entity-id-architecture.test.ts
bun run type-check
```

---

### Task 10: Documentation and Completion Audit

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`
- Modify: `docs/api/openapi.md`
- Modify: `scripts/check_documentation_contracts.py`
- Modify: `backend/tests/test_typed_id_architecture.py`
- Modify: `frontend/types/entity-id-architecture.test.ts`

**Interfaces:**
- Consumes: final production implementation and route inventory.
- Produces: normative documentation and automated checks matching the final boundaries.

- [ ] **Step 1: Document boundary ownership**

Document persistence UUIDs, Python typed IDs, REST DTO serialization,
schema-less strict normalization, frontend branded parsing, and the prohibition
on compatibility serializers.

- [ ] **Step 2: Document public response shapes**

Update `/auth/me`, login, registration, organization, and pagination examples
to use canonical prefixed IDs.

- [ ] **Step 3: Run targeted backend verification**

```bash
cd backend
JOYSAFETER_TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:33972/joysafeter_typed_ids_20260825' \
  .venv/bin/pytest -q \
  tests/test_rest_response_serialization_contract.py \
  tests/test_tenant_auth_rest_id_contract.py \
  tests/test_auth_service_login_tokens.py \
  tests/test_identity_federation_session_gateway.py \
  tests/test_organization_member_error_contract.py \
  tests/test_managed_auth_context_contract.py \
  tests/test_me_capability.py \
  tests/test_entity_ids.py \
  tests/test_typed_id_architecture.py \
  tests/test_id_helper_error_contract.py \
  tests/test_credentials_api.py \
  tests/test_json_boundary.py \
  tests/test_websocket_notification_manager.py \
  tests/test_session_event_batch_id_contract.py \
  tests/test_sse_replay_pagination_contract.py
```

- [ ] **Step 4: Run broader backend verification**

Run typed-ID, auth, organization, credential, session-event, WebSocket, worker,
and API middleware suites. Report unrelated known failures separately.

- [ ] **Step 5: Run static quality checks**

```bash
cd backend
.venv/bin/ruff check \
  app/joysafeter_api/api/v1 \
  app/joysafeter_api/websocket/notification_manager.py \
  app/joysafeter_domain/schemas \
  app/joysafeter_domain/services/joysafeter_auth_service.py \
  app/joysafeter_domain/services/joysafeter_session_service.py \
  app/joysafeter_identity_federation/infrastructure/session_gateway.py \
  app/joysafeter_shared/common \
  app/joysafeter_shared/json_boundary.py \
  tests/test_rest_response_serialization_contract.py \
  tests/test_json_boundary.py
.venv/bin/ruff format --check \
  app/joysafeter_api/api/v1 \
  app/joysafeter_api/websocket/notification_manager.py \
  app/joysafeter_domain/schemas \
  app/joysafeter_domain/services/joysafeter_auth_service.py \
  app/joysafeter_domain/services/joysafeter_session_service.py \
  app/joysafeter_identity_federation/infrastructure/session_gateway.py \
  app/joysafeter_shared/common \
  app/joysafeter_shared/json_boundary.py \
  tests/test_rest_response_serialization_contract.py \
  tests/test_json_boundary.py
cd ..
python3 scripts/check_documentation_contracts.py
```

- [ ] **Step 6: Run frontend verification**

```bash
cd frontend
bun run test -- \
  lib/managed/tenant-response-parsers.test.ts \
  providers/project-provider.test.tsx \
  types/entity-id-architecture.test.ts
bun run type-check
```

- [ ] **Step 7: Perform final semantic and filename scans**

Prove the absence of unreviewed `default=str`, targeted ID encoder bridges,
cursor `str(...)`, REST JSON-mode dumps, removed dictionary helpers,
`_build_jwt_login_response`, `/auth/organizations`, compatibility ID helpers,
and obsolete filenames/directories. Record the owning boundary and test for
every retained match.

- [ ] **Step 8: Reproduce the original request safely**

Use a newly issued local test session rather than the exposed token. Call
`GET /api/v1/auth/me`, verify every ID field is canonical, and revoke the
temporary session.

- [ ] **Step 9: Report completion evidence**

Report root cause, final owners, files changed, commands run, pass/fail counts,
retained allowlist entries, unrelated failures, and deployment/session actions.

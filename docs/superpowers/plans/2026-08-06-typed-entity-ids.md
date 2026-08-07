# Typed Entity ID Value Objects — Implementation Plan

**Status:** Superseded historical implementation plan — non-executable
**Superseded by:** `../specs/2026-08-07-strict-entity-id-boundaries-design.md`

> Preserve this file only as implementation history. Do not execute its commands, recipes, tests, or
> commits. In particular, tolerant string constructors, bare-string acceptance, string SQL binds,
> bare cursors, and compatibility tests below conflict with the strict-boundary design.

> **Historical agent instruction — non-executable:** The original plan required a task-by-task
> execution workflow. Do not resume it; follow the superseding strict-boundary design instead.

**Goal:** Replace bare-`uuid.UUID` identifiers and their scattered
prefix/format/parse/`same_id` helpers with typed `EntityId` value objects that
carry the entity kind in both type and value, end-to-end (request → path →
response → domain → ORM).

**Architecture:** An `EntityId` base class owns parse/format/equality/hash and
the pydantic core schema; per-entity subclasses declare only a `prefix`. A
`TypeDecorator` (`EntityIdType`) maps typed ids to/from the unchanged `UUID`
DB column. A single global `RequestValidationError` handler produces the
canonical `{FIELD}_INVALID` error for every id input.

**Tech Stack:** Python 3.12+, SQLAlchemy 2.x (`Mapped`/`mapped_column`),
Pydantic v2 (`__get_pydantic_core_schema__`), FastAPI, pytest (`asyncio_mode`
config in `backend/pyproject.toml`), `uuid_utils.uuid7`.

## Global Constraints

- **Run tests from `backend/`**: `cd backend && uv run pytest` — never bare
  `pytest` at repo root (config lives only in `backend/pyproject.toml`).
- **No alembic migration**: physical column type stays `UUID(as_uuid=True)`.
- **Error contract shape is frozen**: `code=f"{field.upper()}_INVALID"`,
  `message=f"Invalid {field}: {raw}"`,
  `data={"field": field, field: raw, "expected_prefix": <prefix>}`,
  `source="api"`, `retryable=False`, `user_action="fix_input"`, HTTP 400.
- **Coherence rule**: never leave a `==` (or converted `same_id`) where one side
  is a typed id and the other a bare `uuid.UUID`. Each entity task migrates its
  PK, every FK referencing it, its schema fields, its prefix sites, and the
  `same_id` calls it owns, together.
- **Scope boundary**: `project_id`, `org_id`, `user_id` are `String(255)` — NOT
  migrated. `EntityId` is UUID-backed only.
- **Reuse `uuid_utils.uuid7`** for defaults (matches `JoySafeterBaseModel`).

---

## Per-Entity Migration Recipe

Every entity task (Tasks 4–13) applies this identical mechanical recipe with its
own parameters (class, prefix, files). It is written here once, in full, so an
engineer reading any single entity task has the complete code.

**Parameters per entity:** `<Class>` (e.g. `AgentId`), `<prefix>` (e.g.
`agent_`), `<pk_model>` (the model whose PK this is), `<fk_columns>` (list of
`file:line` FK columns referencing this entity), `<schema_fields>`, `<same_id_sites>`,
`<inline_sites>`, `<format_fn>`/`<parse_fn>` (old helpers for this entity).

**R1. Model PK** (in `<pk_model>`): override the inherited `id`:
```python
id: Mapped[<Class>] = mapped_column(EntityIdType(<Class>), primary_key=True, default=<Class>.new)
```

**R2. FK columns** (each entry in `<fk_columns>`): change the annotation and the
column type, keep `ForeignKey`/`nullable`/`ondelete`:
```python
# before
agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("joysafeter_agents.id"), nullable=False)
# after
agent_id: Mapped[<Class>] = mapped_column(EntityIdType(<Class>), ForeignKey("joysafeter_agents.id"), nullable=False)
# nullable FK:
chat_session_id: Mapped[<Class> | None] = mapped_column(EntityIdType(<Class>), ForeignKey(...), nullable=True)
```

**R3. Pydantic schema fields** (each entry in `<schema_fields>`): change the
field type from `uuid.UUID` to `<Class>` and **delete** the corresponding
`@field_serializer` method (serialization now comes from the core schema):
```python
# before
agent_id: uuid.UUID
@field_serializer("agent_id")
def serialize_agent_id(self, value): return format_agent_id(value)
# after
agent_id: <Class>
```
For request models, likewise change `uuid.UUID`/`Optional[uuid.UUID]` to
`<Class>`/`<Class> | None`.

**R4. `same_id` call sites** (each entry in `<same_id_sites>`): replace with
`==`/`!=`. Both operands are now typed ids of this entity:
```python
# before:  if not same_id(session.agent_id, config.agent.id):
# after:   if session.agent_id != config.agent.id:
```
When a file's **last** `same_id` use is removed, delete the `same_id` import.

**R5. Inline prefix sites** (each entry in `<inline_sites>`): replace hand-rolled
`removeprefix`/`startswith`/f-string prefixing with the value object:

> **Historical/non-executable compatibility recipe:** The constructor examples below tolerated public
> and bare strings. Current code must declare `from_public` versus `from_uuid` explicitly.

```python
# before:  uuid.UUID(req.agent.removeprefix("agent_"))
# after:   <Class>(req.agent).uuid            # tolerant of prefixed or bare
# before:  raw_id if raw_id.startswith("evt_") else f"evt_{raw_id}"
# after:   str(<Class>(raw_id))               # always canonical prefixed form
```

**R6. `format_*` / `parse_*` call sites**: replace with the value object:
```python
# before:  format_task_id(task.id)     -> after:  str(task.id)   # task.id already TaskId
# before:  format_task_id(bare_uuid)   -> after:  str(TaskId(bare_uuid))
# before:  parse_event_id(raw)         -> after:  EventId(raw).uuid   (or keep EventId)
```

**R7. Path-param dependency**: change `id_helpers.parse_<x>` to return the typed
id, or annotate the route param directly as `<x>_id: <Class>`. Keep the
dependency thin; the error contract is produced by the global handler (Task 3).
(The bulk removal of `id_helpers`/`id_utils` happens in Task 14.)

**R8. Per-entity test**: add/adjust a focused test proving the round-trip through
that entity's response serialization still yields `<prefix><uuid>`, then run the
entity's existing tests.

---

## Task 1: `EntityId` value objects module

**Files:**
- Create: `backend/app/joysafeter_shared/ids.py`
- Test: `backend/tests/test_entity_ids.py`

**Interfaces:**
- Produces: `EntityId` base; subclasses `AgentId, SessionId, TaskId,
  EnvironmentId, SecretId, TriggerId, MemoryStoreId, MemoryId, MemoryVersionId,
  SandboxId, VaultId, CredentialId, SkillId, SkillFileId, SkillSecurityScanId,
  EventId, FileId, SessionResourceId`. Each: `__init__(value)`, `.new()`
  classmethod, `.uuid` property, `__str__`, `__eq__`, `__hash__`, and pydantic
  core schema. Consumed by every later task.

- [ ] **Step 1: Write failing tests**

> **Historical/non-executable compatibility tests:** Bare-string constructor acceptance shown below is
> superseded. Public strings require the entity prefix; physical input must be a native UUID.

```python
# backend/tests/test_entity_ids.py
import uuid
import pytest
from pydantic import BaseModel
from app.joysafeter_shared.ids import AgentId, SessionId, TaskId

pytestmark = pytest.mark.no_db


def test_str_roundtrip_adds_prefix():
    u = uuid.uuid4()
    assert str(AgentId(u)) == f"agent_{u}"


def test_accepts_prefixed_string():
    u = uuid.uuid4()
    assert AgentId(f"agent_{u}").uuid == u


def test_accepts_bare_uuid_string():
    u = uuid.uuid4()
    assert AgentId(str(u)).uuid == u


def test_cross_type_inequality():
    u = uuid.uuid4()
    assert AgentId(u) != SessionId(u)


def test_cross_entity_construction_raises():
    with pytest.raises(TypeError):
        AgentId(SessionId(uuid.uuid4()))


def test_wrong_prefix_rejected():
    with pytest.raises(ValueError):
        AgentId(f"sesn_{uuid.uuid4()}")


def test_new_is_unique_and_typed():
    a, b = AgentId.new(), AgentId.new()
    assert isinstance(a, AgentId) and a != b


def test_hash_by_type_and_uuid():
    u = uuid.uuid4()
    assert hash(AgentId(u)) == hash(AgentId(u))
    assert hash(AgentId(u)) != hash(SessionId(u))


def test_pydantic_validate_and_serialize():
    class M(BaseModel):
        id: TaskId
    u = uuid.uuid4()
    m = M(id=f"task_{u}")
    assert m.id == TaskId(u)
    assert m.model_dump(mode="json")["id"] == f"task_{u}"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd backend && uv run pytest tests/test_entity_ids.py -v`
Expected: FAIL — `ModuleNotFoundError: app.joysafeter_shared.ids`.

- [ ] **Step 3: Implement `ids.py` (value objects + pydantic schema)**

```python
# backend/app/joysafeter_shared/ids.py
"""Typed entity identifiers.

Single source of truth for public-facing prefixed IDs. Each entity has a
subclass carrying the entity kind in its type (static safety) and value
(serialization/equality). Physical storage remains a bare UUID.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema
from uuid_utils import uuid7


class EntityId:
    prefix: ClassVar[str]
    __slots__ = ("_uuid",)

    def __init__(self, value: uuid.UUID | str | "EntityId") -> None:
        self._uuid = self._coerce(value)

    @classmethod
    def _coerce(cls, value: Any) -> uuid.UUID:
        if isinstance(value, EntityId):
            if type(value) is not cls:
                raise TypeError(
                    f"cannot build {cls.__name__} from {type(value).__name__}"
                )
            return value._uuid
        if isinstance(value, uuid.UUID):
            return value
        s = str(value)
        if s.startswith(cls.prefix):
            s = s[len(cls.prefix):]
        return uuid.UUID(s)  # raises ValueError on non-uuid remainder

    @classmethod
    def new(cls) -> "EntityId":
        return cls(uuid.UUID(str(uuid7())))

    @property
    def uuid(self) -> uuid.UUID:
        return self._uuid

    def __str__(self) -> str:
        return f"{self.prefix}{self._uuid}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._uuid})"

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self._uuid == other._uuid  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self), self._uuid))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: Any) -> "EntityId":
            if isinstance(value, cls):
                return value
            return cls(value)

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema(), when_used="json-unless-none"
            ),
        )


class AgentId(EntityId):              prefix = "agent_"
class SessionId(EntityId):            prefix = "sess_"
class TaskId(EntityId):               prefix = "task_"
class EnvironmentId(EntityId):        prefix = "env_"
class SecretId(EntityId):             prefix = "secret_"
class TriggerId(EntityId):            prefix = "trig_"
class MemoryStoreId(EntityId):        prefix = "memstore_"
class MemoryId(EntityId):             prefix = "mem_"
class MemoryVersionId(EntityId):      prefix = "memver_"
class SandboxId(EntityId):            prefix = "sbx_"
class VaultId(EntityId):              prefix = "vault_"
class CredentialId(EntityId):         prefix = "cred_"
class SkillId(EntityId):              prefix = "skill_"
class SkillFileId(EntityId):          prefix = "sklfile_"
class SkillSecurityScanId(EntityId):  prefix = "sklscan_"
class EventId(EntityId):              prefix = "evt_"
class FileId(EntityId):               prefix = "file_"
class SessionResourceId(EntityId):    prefix = "sesrsc_"
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_entity_ids.py -v`
Expected: PASS (all 9).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/ids.py backend/tests/test_entity_ids.py
git commit -m "feat(ids): add EntityId value objects with pydantic schema"
```

---

## Task 2: `EntityIdType` SQLAlchemy TypeDecorator

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py` (append `EntityIdType`)
- Test: `backend/tests/test_entity_id_type.py`

**Interfaces:**
- Consumes: `EntityId` subclasses from Task 1.
- Produces: `EntityIdType(id_cls)` — a `TypeDecorator` over `UUID(as_uuid=True)`;
  `process_bind_param(EntityId|uuid|str|None) -> uuid|None`,
  `process_result_value(uuid|None) -> EntityId|None`. Consumed by all model tasks.

- [ ] **Step 1: Write failing tests**

> **Historical/non-executable compatibility tests:** String/native fallback binds shown below are
> superseded. SQL bind/result conversion accepts the concrete typed ID or native UUID only.

```python
# backend/tests/test_entity_id_type.py
import uuid
import pytest
from app.joysafeter_shared.ids import AgentId, EntityIdType

pytestmark = pytest.mark.no_db


def test_bind_unwraps_typed_id():
    t = EntityIdType(AgentId)
    u = uuid.uuid4()
    assert t.process_bind_param(AgentId(u), None) == u


def test_bind_accepts_bare_uuid_and_str():
    t = EntityIdType(AgentId)
    u = uuid.uuid4()
    assert t.process_bind_param(u, None) == u
    assert t.process_bind_param(f"agent_{u}", None) == u


def test_bind_none_passthrough():
    assert EntityIdType(AgentId).process_bind_param(None, None) is None


def test_result_wraps_into_typed_id():
    t = EntityIdType(AgentId)
    u = uuid.uuid4()
    got = t.process_result_value(u, None)
    assert got == AgentId(u) and isinstance(got, AgentId)


def test_result_none_passthrough():
    assert EntityIdType(AgentId).process_result_value(None, None) is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd backend && uv run pytest tests/test_entity_id_type.py -v`
Expected: FAIL — `ImportError: cannot import name 'EntityIdType'`.

- [ ] **Step 3: Append `EntityIdType` to `ids.py`**

```python
# append to backend/app/joysafeter_shared/ids.py
from sqlalchemy.dialects.postgresql import UUID as _PgUUID
from sqlalchemy.types import TypeDecorator


class EntityIdType(TypeDecorator):
    """Store an EntityId as a native UUID column; hydrate back to the typed id."""

    impl = _PgUUID(as_uuid=True)
    cache_ok = True

    def __init__(self, id_cls: type[EntityId]) -> None:
        self.id_cls = id_cls
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, EntityId):
            return value.uuid
        return self.id_cls(value).uuid

    def process_result_value(self, value, dialect):
        return None if value is None else self.id_cls(value)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/test_entity_id_type.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/ids.py backend/tests/test_entity_id_type.py
git commit -m "feat(ids): add EntityIdType TypeDecorator for the ORM boundary"
```

---

## Task 3: Unified id validation error handler

**Files:**
- Modify: `backend/app/joysafeter_api/app.py` (register handler)
- Create: `backend/app/joysafeter_api/id_validation_error.py` (handler logic)
- Test: `backend/tests/test_id_validation_error_contract.py`

**Interfaces:**
- Consumes: `EntityId` subclasses (to detect prefix / entity in a failed
  validation) from Task 1.
- Produces: FastAPI exception behavior — any `RequestValidationError` whose
  failing field is an `EntityId` subclass yields the frozen `{FIELD}_INVALID`
  400 payload. Consumed implicitly by every route using typed ids.

**Note:** Locate the existing `RequestValidationError` handler in
`joysafeter_api/app.py` first (`grep -n "RequestValidationError\|exception_handler" backend/app/joysafeter_api/app.py`).
This task wraps/extends it, delegating non-id errors to the existing behavior.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_id_validation_error_contract.py
import uuid
import pytest
from error_contract_helpers import handled_app_error_payload
from app.joysafeter_api.id_validation_error import app_error_for_id_validation
from app.joysafeter_shared.ids import AgentId

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_agent_id_invalid_maps_to_canonical_contract():
    # Simulated pydantic error loc/input for an AgentId field named "agent_id".
    err = {"loc": ("body", "agent_id"), "input": "agent_not-a-uuid", "ctx": {"id_cls": AgentId}}
    app_error = app_error_for_id_validation(err)
    assert app_error is not None
    assert await handled_app_error_payload(app_error, status_code=400) == {
        "code": "AGENT_ID_INVALID",
        "message": "Invalid agent_id: agent_not-a-uuid",
        "data": {"field": "agent_id", "agent_id": "agent_not-a-uuid", "expected_prefix": "agent_"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd backend && uv run pytest tests/test_id_validation_error_contract.py -v`
Expected: FAIL — module/function not found.

- [ ] **Step 3: Implement handler logic**

The `EntityId.__get_pydantic_core_schema__` validator must attach the id class
to the error so the handler can recover it. Update the validator in `ids.py` to
raise with context, and add the mapper. In `ids.py`, change `validate` to:

```python
        def validate(value: Any) -> "EntityId":
            if isinstance(value, cls):
                return value
            try:
                return cls(value)
            except (ValueError, TypeError):
                raise ValueError(f"__entity_id__:{cls.__name__}")  # marker for the handler
```

```python
# backend/app/joysafeter_api/id_validation_error.py
from typing import Any, Optional

from app.joysafeter_shared.common.app_errors import AppError, InvalidRequestError
from app.joysafeter_shared import ids as _ids


def _id_cls_from_error(err: dict) -> Optional[type]:
    ctx = err.get("ctx") or {}
    if isinstance(ctx.get("id_cls"), type):
        return ctx["id_cls"]
    msg = str(ctx.get("error") or err.get("msg") or "")
    marker = "__entity_id__:"
    if marker in msg:
        name = msg.split(marker, 1)[1].strip().split()[0]
        return getattr(_ids, name, None)
    return None


def app_error_for_id_validation(err: dict) -> Optional[AppError]:
    id_cls = _id_cls_from_error(err)
    if id_cls is None:
        return None
    field = str(err["loc"][-1])
    raw = err.get("input")
    return InvalidRequestError(
        code=f"{field.upper()}_INVALID",
        message=f"Invalid {field}: {raw}",
        data={"field": field, field: raw, "expected_prefix": id_cls.prefix},
        user_action="fix_input",
    )
```

- [ ] **Step 4: Run unit test, verify pass**

Run: `cd backend && uv run pytest tests/test_id_validation_error_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into the app's validation handler**

In `backend/app/joysafeter_api/app.py`, inside the existing
`RequestValidationError` handler, iterate `exc.errors()`, and for the first
error where `app_error_for_id_validation(err)` is not `None`, render that
`AppError` (reuse the existing AppError→response path); otherwise fall through
to current behavior. Add an integration test hitting a real route with a bad
prefixed id (pick one already migrated after Task 4, or a temporary test route)
asserting HTTP 400 + `AGENT_ID_INVALID`.

- [ ] **Step 6: Run full no-db suite, commit**

Run: `cd backend && uv run pytest tests/test_id_validation_error_contract.py tests/test_entity_ids.py -v`
Expected: PASS.

```bash
git add backend/app/joysafeter_api/id_validation_error.py backend/app/joysafeter_api/app.py backend/app/joysafeter_shared/ids.py backend/tests/test_id_validation_error_contract.py
git commit -m "feat(ids): unified id validation error contract for body and path"
```

---

## Task 4: Migrate **Agent** entity (worked template)

Apply the Per-Entity Migration Recipe with these parameters. This task is the
full worked example; Tasks 5–13 follow the same recipe.

**Parameters:**
- `<Class>` = `AgentId`, `<prefix>` = `agent_`
- `<pk_model>`: `backend/app/joysafeter_domain/models/joysafeter_agent.py` (its `id`)
- `<fk_columns>`:
  - `models/joysafeter_task.py:98-102` `agent_id`
  - `models/joysafeter_session.py` `agent_id` (grep `agent_id` in the file)
  - any other `ForeignKey("joysafeter_agents.id")` (grep it)
- `<schema_fields>`: `schemas/joysafeter_task.py:51` (`agent_id`) + serializer
  `:74-76`; `schemas/joysafeter_task.py:28` (`JoySafeterCreateTaskRequest.agent_id`);
  `schemas/analytics.py:107` serializer + its field; any agent schema `id` field.
- `<same_id_sites>`:
  - `services/agent_trigger_execution.py:143`, `:159`
  - `api/v1/tasks.py:185`, `:408`
- `<inline_sites>`:
  - `api/v1/sessions.py:305` `uuid.UUID(req.agent.removeprefix("agent_"))` → `AgentId(req.agent).uuid`
  - `schemas/joysafeter_session.py:225` `raw.removeprefix("agent_")` → `AgentId(raw).uuid`
- `<format_fn>`/`<parse_fn>`: `format_agent_id` (id_utils), `parse_agent_id` (id_helpers)

**Files:**
- Modify: `models/joysafeter_agent.py`, `models/joysafeter_task.py`,
  `models/joysafeter_session.py`, `schemas/joysafeter_task.py`,
  `schemas/analytics.py`, `schemas/joysafeter_session.py`,
  `services/agent_trigger_execution.py`, `api/v1/tasks.py`, `api/v1/sessions.py`,
  `api/v1/id_helpers.py` (`parse_agent_id` returns `AgentId`)
- Test: `tests/test_id_helper_error_contract.py` (agent assertions),
  existing agent/task tests.

- [ ] **Step 1: Write/adjust the failing test**

Prove agent id round-trips through the task response as `agent_<uuid>` with the
field now typed:

```python
# add to tests covering task response, e.g. tests/test_entity_ids.py or a task test
def test_task_response_serializes_agent_id_prefix():
    import uuid
    from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse
    from app.joysafeter_shared.ids import AgentId, TaskId
    aid, tid = uuid.uuid4(), uuid.uuid4()
    resp = JoySafeterTaskResponse.model_validate({
        "id": TaskId(tid), "agent_id": AgentId(aid), "status": "completed",
        "prompt": "x", "timeout_sec": 1, "retry_count": 0, "max_retries": 0,
        "created_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
    })
    assert resp.model_dump(mode="json")["agent_id"] == f"agent_{aid}"
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd backend && uv run pytest tests/test_entity_ids.py::test_task_response_serializes_agent_id_prefix -v`
Expected: FAIL (field still `uuid.UUID`, or validate rejects `AgentId`).

- [ ] **Step 3: Apply recipe R1–R7 for Agent**

- R1: in `joysafeter_agent.py`, override `id` → `Mapped[AgentId] = mapped_column(EntityIdType(AgentId), primary_key=True, default=AgentId.new)`. Import `AgentId, EntityIdType` from `app.joysafeter_shared.ids`.
- R2: change every `<fk_columns>` entry to `Mapped[AgentId]`/`Mapped[AgentId | None]` + `EntityIdType(AgentId)`.
- R3: in `joysafeter_task.py` schema, `agent_id: AgentId`, delete `serialize_agent_id`; `JoySafeterCreateTaskRequest.agent_id: AgentId | None = None`; in `analytics.py` type the field + delete `serialize_agent_id`.
- R4: `agent_trigger_execution.py:143/159` → `session.agent_id != config.agent.id`; `tasks.py:185` → `existing.agent_id != req.agent_id`; `tasks.py:408` → `existing_session.agent_id != agent.id`. Remove `same_id` import from a file only when its last use is gone (agent_trigger_execution still has a Session use at :262 → keep import until Task 5).
- R5: apply the two `<inline_sites>` rewrites.
- R7: `id_helpers.parse_agent_id` → `return AgentId(agent_id)` (drop the manual `_strip_prefix`; the global handler now owns the error contract). Keep it as a dependency for now.

- [ ] **Step 4: Update the agent error-contract assertion**

In `tests/test_id_helper_error_contract.py`, the direct
`parse_agent_id("agent_not-a-uuid")` test now expects `AgentId(...)` to raise
`ValueError`/`AppError` via the route. Change this assertion to drive the route
(or `app_error_for_id_validation`) per Task 3's pattern, keeping the same payload.

- [ ] **Step 5: Run agent-scoped tests, verify pass**

Run: `cd backend && uv run pytest tests/test_entity_ids.py tests/test_id_helper_error_contract.py -k "agent" -v`
Expected: PASS.

- [ ] **Step 6: Run the broader affected suites**

Run: `cd backend && uv run pytest tests/test_agent_lifecycle_active_tasks.py tests/test_agent_environment_ref_validation.py -v`
Expected: PASS (fix any typed/bare fallout before proceeding).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(ids): migrate Agent identifiers to AgentId value object"
```

---

## Task 5: Migrate **Session** entity

Apply the recipe with:
- `<Class>` = `SessionId`, `<prefix>` = `sess_`
- `<pk_model>`: `models/joysafeter_session.py` `id`
- `<fk_columns>`: `models/joysafeter_task.py:103-107` `chat_session_id`;
  `models/joysafeter_session_file.py` / `joysafeter_file.py` `session_id`
  (grep `ForeignKey("joysafeter_sessions.id")`).
- `<schema_fields>`: `schemas/joysafeter_task.py:52` `chat_session_id` + serializer
  `:78-80`; `JoySafeterCreateTaskRequest.chat_session_id` (`:32`);
  `analytics.py:103` serializer + field; `schemas/joysafeter_file.py` `session_id`
  (`FileResponse.from_model`).
- `<same_id_sites>`: `agent_trigger_execution.py:262`;
  `task_submission_service.py:261`, `:277`; `joysafeter_session_service.py:531`;
  `api/v1/tasks.py:193`; `api/v1/sessions.py:1320`. After these, remove the
  `same_id` import from `agent_trigger_execution.py`, `task_submission_service.py`,
  `joysafeter_session_service.py`, `sessions.py` **if** no other same_id remains
  in each (tasks.py still has Environment at :248 → keep there until Task 8).
- `<inline_sites>`: `api/v1/files.py:59` `scope_id.removeprefix("sess_")` →
  `SessionId(scope_id).uuid`; `sessions.py:85` is `env_` (Task 8, not here).
- `<format_fn>`/`<parse_fn>`: `format_session_id`, `parse_session_id`.

**Steps:** identical shape to Task 4 (write failing session-serialization test →
verify fail → apply R1–R7 → update session error-contract assertions →
`cd backend && uv run pytest tests/test_environment_lifecycle_active_sessions.py tests/test_id_helper_error_contract.py -k "session" -v` → commit
`refactor(ids): migrate Session identifiers to SessionId value object`).

---

## Task 6: Migrate **Task** entity (+ cursor)

Apply the recipe with:
- `<Class>` = `TaskId`, `<prefix>` = `task_`
- `<pk_model>`: `models/joysafeter_task.py` `id`
- `<fk_columns>`: any `ForeignKey("joysafeter_tasks.id")` (grep); plus
  `last_task_id`/`task_id` on `SandboxResponse` / network policy (these are
  schema fields, R3).
- `<schema_fields>`: `schemas/joysafeter_task.py:41` (`JoySafeterCreateTaskResponse.id`)
  + serializer `:44-46`; `:50` (`JoySafeterTaskResponse.id`) + serializer `:70-72`;
  `analytics.py:99` (`id`, `trace_id`) + serializer; `SandboxResponse.last_task_id`,
  `NetworkPolicyStatusResponse.task_id` (drop their `field_serializer`s).
- `<same_id_sites>`: none owned by Task.
- `<format_fn>` sites (R6, many — all become `str(<TaskId>)`):
  `services/joysafeter_trigger_service.py:152`; `task_submission_service.py:43,57,212,217,238,274,282`;
  `task_cancellation_service.py:64,72,163,232,238,249`; `api/v1/agents.py:421,478,549`;
  `api/v1/environments.py:59`; `api/v1/secrets.py:69`. For each: if the value is
  already a `TaskId` (e.g. `task.id`), use `str(task.id)`; if it is a bare uuid
  (a function parameter), use `str(TaskId(task_id))`.
- **Cursor:** `id_helpers.parse_task_after_id` must keep accepting `task_<uuid>`,
- **Historical/non-executable cursor compatibility:** The former step accepted `task_<uuid>`, a bare
  UUID, and `None`. It is superseded: public cursors accept only canonical `task_<uuid>` values (or
  `None`) through strict public parsing.

**Steps:** write failing task-response test (`JoySafeterCreateTaskResponse` dumps
`task_<uuid>`) → verify fail → apply R1/R3/R6 + cursor → update task
error-contract assertions (`test_id_helper_error_contract.py:54-65,81-109`) →
`cd backend && uv run pytest tests/test_id_helper_error_contract.py tests/test_foundation2_task_idempotency.py tests/test_task_prompt_size_cap_contract.py -v` →
commit `refactor(ids): migrate Task identifiers to TaskId value object`.

---

## Task 7: Migrate **Trigger** entity

- `<Class>` = `TriggerId`, `<prefix>` = `trig_`
- `<pk_model>`: `models/joysafeter_trigger.py` `id`
- `<fk_columns>`: `models/joysafeter_task.py:132-136` `trigger_id`
  (`ondelete="SET NULL"`, nullable).
- `<schema_fields>`: trigger schemas' `id`/`trigger_id` (grep `trigger` in
  `schemas/`), drop any `field_serializer`.
- `<same_id_sites>`: `services/joysafeter_trigger_service.py:371`
  → `existing.id != trigger_id`; then remove `same_id` from its import
  (`:27`), leaving `format_task_id` (already handled in Task 6).
- `<parse_fn>`: `parse_trigger_id`.

**Steps:** failing trigger-serialization test → apply R1–R7 →
`cd backend && uv run pytest tests/test_trigger_schema_contract.py tests/test_trigger_http_error_contract.py tests/test_trigger_project_lifecycle.py tests/test_trigger_webhook_route_contract.py -v` →
commit `refactor(ids): migrate Trigger identifiers to TriggerId value object`.

---

## Task 8: Migrate **Environment** entity

- `<Class>` = `EnvironmentId`, `<prefix>` = `env_`
- `<pk_model>`: `models/joysafeter_environment.py` `id`
- `<fk_columns>`: any `ForeignKey("joysafeter_environments.id")` (grep).
- `<schema_fields>`: environment schemas' `id`; `environments.py:59` already
  handled as a Task field in Task 6 (it's a `task_id`); the environment's own id.
- `<same_id_sites>`: `api/v1/tasks.py:248`
  → `effective_environment.id == requested_environment.id`; this is tasks.py's
  **last** same_id → now remove `same_id` import from `tasks.py:37`.
- `<inline_sites>`: `services/joysafeter_environment_service.py:77-79`
  (`normalized.startswith("env_")` / `removeprefix("env_")`) →
  `EnvironmentId(normalized).uuid`; `api/v1/sessions.py:85`
  `uuid.UUID(ref.removeprefix("env_"))` → `EnvironmentId(ref).uuid`.
- `<parse_fn>`: `parse_env_id`.

**Steps:** failing env-serialization test → apply R1–R7 →
`cd backend && uv run pytest tests/test_agent_environment_ref_validation.py tests/test_environment_lifecycle_active_sessions.py -v` →
commit `refactor(ids): migrate Environment identifiers to EnvironmentId value object`.

---

## Task 9: Migrate **Sandbox** entity

- `<Class>` = `SandboxId`, `<prefix>` = `sbx_`
- `<pk_model>`: `models/joysafeter_sandbox.py` `id`
- `<fk_columns>`: `models/joysafeter_task.py:111` `sandbox_id` (no FK constraint,
  still `EntityIdType(SandboxId)`, nullable); `sandbox_network_policy` `sandbox_id`.
- `<schema_fields>`: `schemas/joysafeter_task.py:56` `sandbox_id` + serializer
  `:82-84`; `SandboxResponse.id`, `NetworkPolicyStatusResponse.sandbox_id` (drop
  serializers).
- `<format_fn>` sites (R6): `task_cancellation_service.py:76,165`;
  `api/v1/agents.py:550` — `str(<SandboxId>)`.
- `<parse_fn>`: `parse_sandbox_id`.

**Steps:** failing sandbox-serialization test → apply R1/R2/R3/R6 →
`cd backend && uv run pytest tests/test_id_helper_error_contract.py -k "sandbox or task" -v` →
commit `refactor(ids): migrate Sandbox identifiers to SandboxId value object`.

---

## Task 10: Migrate **Secret**, **Vault**, **Credential**

Three small entities, one commit (no `same_id`, few sites).
- `SecretId`/`secret_`: `models/joysafeter_secret.py` PK; secret schemas; `parse_secret_id`.
- `VaultId`/`vault_`: `models/joysafeter_vault.py` PK; vault schemas;
  `api/v1/sessions.py:417` `vid_raw.removeprefix("vault_")` → `VaultId(vid_raw).uuid`;
  `parse_vault_id`.
- `CredentialId`/`cred_`: credential model/schema; `parse_cred_id`.

**Steps:** failing serialization tests (one per entity) → apply R1–R7 →
`cd backend && uv run pytest tests/test_secret_lifecycle_active_dependencies.py tests/test_secret_connectivity.py tests/test_credential_masking_default_deny.py tests/test_id_helper_error_contract.py -k "vault or secret or cred" -v` →
commit `refactor(ids): migrate Secret/Vault/Credential identifiers`.

---

## Task 11: Migrate **Memory** trio (Store, Memory, Version)

- `MemoryStoreId`/`memstore_`, `MemoryId`/`mem_`, `MemoryVersionId`/`memver_`
- `<pk_model>`s: `models/joysafeter_memory.py` (store, memory, version PKs + FKs
  between them — grep `ForeignKey` in the file; version→memory, memory→store).
- `<schema_fields>`: `schemas/joysafeter_memory.py` id fields, drop serializers.
- `<parse_fn>`: `parse_memory_store_id`, `parse_memory_id`, `parse_memory_version_id`.

**Steps:** failing serialization test per id → apply R1–R7 →
`cd backend && uv run pytest tests/test_memory_store_lifecycle_active_sessions.py tests/test_id_helper_error_contract.py -k "memory" -v` →
commit `refactor(ids): migrate Memory identifiers (store/memory/version)`.

---

## Task 12: Migrate **Skill** trio (Skill, SkillFile, SkillSecurityScan)

- `SkillId`/`skill_`, `SkillFileId`/`sklfile_`, `SkillSecurityScanId`/`sklscan_`
- `<pk_model>`s: `models/joysafeter_skill.py` PKs + FKs (file→skill, scan→skill).
- `<schema_fields>`: skill schemas' ids, drop serializers.
- `<inline_sites>`: `services/joysafeter_skill_service.py:930`
  `uuid.UUID(str(value).removeprefix("skill_")) == skill_id` →
  `SkillId(value) == skill_id` (ensure `skill_id` is a `SkillId` here);
  `services/joysafeter_agent_service.py:129`
  `uuid.UUID(str(value).removeprefix("skill_"))` → `SkillId(value).uuid`;
  `api/v1/skills_ai_authoring.py:138`
  `raw.removeprefix("skill_") if raw.startswith("skill_") else raw` →
  `str(SkillId(raw).uuid)` (or return `SkillId(raw)` if the caller wants the id).
- `<parse_fn>`: `parse_skill_id`, `parse_skill_file_id`, `parse_skill_security_scan_id`.

**Steps:** failing serialization test per id → apply R1–R7 →
`cd backend && uv run pytest tests/services/test_skill_usage_route_contract.py tests/test_id_helper_error_contract.py -k "skill" -v` →
commit `refactor(ids): migrate Skill identifiers (skill/file/scan)`.

---

## Task 13: Migrate **Event**, **File**, **SessionResource**

- `EventId`/`evt_`:
  - `services/joysafeter_session_service.py:781` `parse_event_id(raw_tool_use_id)`
    → `EventId(raw_tool_use_id).uuid`; drop `parse_event_id` import.
  - `:34` `raw_id if raw_id.startswith("evt_") else f"evt_{raw_id}"`
    → `str(EventId(raw_id))`.
  - `api/v1/sessions.py:2048` `event_id and not event_id.startswith("evt_")`
    → normalize via `str(EventId(event_id))` (preserve the surrounding intent —
    read the block first).
- `FileId`/`file_`:
  - `api/v1/files.py:35` `raw.removeprefix("file_")` → `FileId(raw).uuid`.
  - `services/joysafeter_session_resource_service.py:584` `raw.removeprefix("file_")`
    → `FileId(raw).uuid`.
  - `models/joysafeter_file.py` PK → `FileId`; `schemas/joysafeter_file.py`
    `id`/`FileResponse` fields.
- `SessionResourceId`/`sesrsc_`:
  - `services/joysafeter_session_resource_service.py:600` `raw.removeprefix("sesrsc_")`
    → `SessionResourceId(raw).uuid`; model PK if one exists.

**Steps:** failing serialization/round-trip test per id → apply relevant recipe
steps → `cd backend && uv run pytest tests/test_session_message_dispatch_failure.py tests/test_id_helper_error_contract.py -k "file or session" -v` →
commit `refactor(ids): migrate Event/File/SessionResource identifiers`.

---

## Task 14: Teardown, contract-test rewrite, and full sweep

**Files:**
- Delete/shrink: `backend/app/joysafeter_shared/utils/id_utils.py`,
  `backend/app/joysafeter_api/api/v1/id_helpers.py`
- Rewrite: `backend/tests/test_id_helper_error_contract.py`
- Verify: whole suite

- [ ] **Step 1: Confirm nothing imports the dead helpers**

Run:
```bash
cd backend && rg -n "same_id|format_agent_id|format_session_id|format_task_id|format_sandbox_id|format_prefixed_id|parse_event_id" app/ ; echo "exit=$?"
```
Expected: no matches (exit=1). Fix any stragglers before deleting.

- [ ] **Step 2: Sweep for any remaining inline prefix literal**

Run:
```bash
cd backend && rg -n 'removeprefix\("[a-z]+_"\)|startswith\("[a-z]+_"\)|f"[a-z]+_\{' app/joysafeter_domain app/joysafeter_api
```
Expected: only non-id prefixes remain (auth `Bearer `, `sha256=`, `/workspace`,
`Environment is referenced`, redis `joysafeter:instances:`, LLM `data: `, etc.).
Any id prefix (matching the inventory table) is a miss → fold into its `EntityId`.

- [ ] **Step 3: Delete the dead helper functions**

Remove `same_id`, `format_*`, `parse_event_id`, `format_prefixed_id`,
`_parse_prefixed_id` from `id_utils.py` (delete the file if empty). Replace the
`id_helpers.py` `parse_*` dependencies: either delete the file and annotate
route params directly as `<x>_id: <Class>`, or keep thin one-liners
`return <Class>(x)`. Choose per how routes consume them (grep
`Depends(parse_` to see call sites).

- [ ] **Step 4: Rewrite the error-contract test to the unified exit**

`test_id_helper_error_contract.py` now asserts the frozen payloads by driving
request validation (or `app_error_for_id_validation`) rather than calling the
deleted `parse_*` functions directly. Keep every asserted payload byte-identical
to the current file (codes, messages, `data`, `user_action`). Keep the
  historical compatibility tests (`parse_task_after_id` bare+prefixed+None; serialized
  `agent_`/`sess_`/`task_` prefixes in `analytics`, `SandboxResponse`,
  `NetworkPolicyStatusResponse`, `FileResponse`) are non-executable as written; strict tests replace
  the bare-cursor case with rejection and retain canonical serialization coverage.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && uv run pytest`
Expected: PASS. Investigate any typed/bare `==` fallout (a comparison returning
`False` where equality was expected → an unmigrated site).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(ids): remove legacy id helpers; unify id error-contract test"
```

---

## Self-Review

- **Spec coverage:** value object (T1) ✓; pydantic (T1) ✓; TypeDecorator (T2) ✓;
  unified error contract (T3) ✓; all 18 inventory entities (T4–T13) ✓; `same_id`
  removal + inline scatter (T4–T14) ✓; `parse_task_after_id` cursor + removed-prefix
  rejection (T6, T14) ✓; contract-test rewrite (T14) ✓; scope boundary for String
  ids (Global Constraints) ✓; coherence rule (per-entity ownership) ✓.
- **Placeholders:** none — each mechanical step points to the complete Recipe
  code and exact `file:line` targets.
- **Type consistency:** `EntityId`, `.uuid`, `.new()`, `EntityIdType(id_cls)`,
  `app_error_for_id_validation(err)` names are stable across all tasks.

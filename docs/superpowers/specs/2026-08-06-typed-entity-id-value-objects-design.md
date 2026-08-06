# Typed Entity ID Value Objects — Design Spec

**Date:** 2026-08-06
**Status:** Approved (design), pending implementation plan
**Scope:** Full-chain (请求体 → 路径参数 → 响应体 → domain service → ORM)

## Problem / Root Cause

Identifiers throughout the backend are bare `uuid.UUID`. The information "which
entity this id belongs to" is **not modeled as a type** — it only exists as a
string prefix (`agent_`, `sess_`, ...) that is bolted on at the edges by a
scatter of free functions, and stripped back off by another scatter. This is
**primitive obsession**: one primitive (`uuid.UUID`) is overloaded to mean ~18
different kinds of identity, and the disambiguation lives in the programmer's
head plus ad-hoc string helpers.

Three observable symptoms, all projections of that one root cause:

1. **Prefixes can lie.** `format_agent_id(value)` takes `Any` and just
   concatenates; nothing binds the prefix to the id's real entity. Passing a
   session uuid produces `agent_<session-uuid>` silently.
2. **`same_id` compares by `str()`** (`id_utils.py:9`). A formatted
   `"sess_xxx"` vs a bare `UUID("xxx")` compares unequal for the same entity;
   and it happily compares an agent id against a task id — no type guard.
3. **The prefix registry is scattered and asymmetric.** Formatting lives in
   `id_utils.py`, parsing in `id_helpers.py`, and *additional inline copies*
   are spread across services and schemas (see Inventory). `parse_event_id`
   exists with no `format_event_id`; many `parse_*` have no `format_*`. Drift
   is guaranteed.

## Chosen Approach: Typed ID value objects (base class + subclasses)

An `EntityId` base class owns all behavior (parse / format / equality /
hashing / pydantic schema) via **inheritance + polymorphism**; each concrete
subclass declares only its `prefix`. The subclass's *type identity* provides
static distinction; the base's shared logic is written once.

This is the only option that satisfies both requirements simultaneously:
- the id's **kind** is part of its **type** (static safety — mypy/pyright catch
  passing a `SessionId` where an `AgentId` is expected), AND
- the kind is carried in the **value** (correct serialization and equality).

(`NewType` gives static distinction but no behavior/prefix; a single generic
`EntityId(kind=...)` runtime field gives behavior but no static safety. Only
the base-class + subclass shape gives both.)

### Scope boundary

`EntityId` is for **UUID-backed** entities only. `project_id`, `org_id`,
`user_id` are `String(255)` columns (see `joysafeter_task.py:87-97`) and are
**out of scope** — they keep their current string handling.

## The value object

New module `backend/app/joysafeter_shared/ids.py`:

```python
class EntityId:
    prefix: ClassVar[str]              # the only thing subclasses declare
    __slots__ = ("_uuid",)

    def __init__(self, value: uuid.UUID | str | "EntityId"):
        self._uuid = self._coerce(value)

    @classmethod
    def _coerce(cls, value) -> uuid.UUID:
        if isinstance(value, EntityId):
            if type(value) is not cls:            # cross-entity construction is a loud error
                raise TypeError(f"cannot build {cls.__name__} from {type(value).__name__}")
            return value._uuid
        if isinstance(value, uuid.UUID):
            return value
        s = str(value)
        s = s[len(cls.prefix):] if s.startswith(cls.prefix) else s
        return uuid.UUID(s)                        # raises ValueError on garbage

    @classmethod
    def new(cls) -> "EntityId":
        return cls(uuid7())                        # reuse existing uuid_utils.uuid7

    @property
    def uuid(self) -> uuid.UUID:
        return self._uuid

    def __str__(self) -> str:  return f"{self.prefix}{self._uuid}"
    def __repr__(self) -> str: return f"{type(self).__name__}({self._uuid})"
    def __eq__(self, o):       return type(self) is type(o) and self._uuid == o._uuid
    def __hash__(self):        return hash((type(self), self._uuid))
```

Equality includes the concrete type, so `AgentId(x) != SessionId(x)` at
runtime, and comparing the two is a static type error under strict-equality.

## Integration point 1 — Pydantic (request + response)

`EntityId` implements `__get_pydantic_core_schema__` **once** on the base:
- validation: accept `agent_<uuid>` **or** a bare uuid, produce the typed id;
- serialization: emit `str(self)` → `agent_<uuid>`.

Consequences:
- All `@field_serializer` id methods are **deleted** (`joysafeter_task.py:44-84`,
  `analytics.py:99-107`, and any others); the field type is just `AgentId`.
- Request-body id fields (e.g. `JoySafeterCreateTaskRequest.agent_id`,
  currently bare `uuid.UUID` at `joysafeter_task.py:28`) become typed ids,
  giving full-chain consistency.

## Integration point 2 — Unified error contract (the crux of full-chain)

Full-chain typing forces error-handling to be unified, otherwise the current
split (path params → structured `400 *_INVALID` via `id_helpers`; body →
pydantic `422`) merely moves the inconsistency around.

Resolution — one error exit for **all** id inputs (body and path):
1. The `EntityId` pydantic validator raises a validation error carrying enough
   info (it knows its own `prefix`).
2. A **global `RequestValidationError` handler** detects failures whose target
   type is an `EntityId` subclass and reshapes them into the existing canonical
   payload:
   - `code`: `f"{field.upper()}_INVALID"`
   - `message`: `f"Invalid {field}: {raw}"`
   - `data`: `{"field": field, field: raw, "expected_prefix": <subclass>.prefix}`
   - `status`: 400, `source`: `api`, `retryable`: false, `user_action`: `fix_input`
   - `field` derived from the validation error `loc`; `expected_prefix` from the
     subclass.
3. Path params are annotated directly as `agent_id: AgentId`; the 18 `parse_*`
   functions and `_invalid_id_error` in `id_helpers.py` are **replaced** by this
   single mechanism.

The **externally visible error shape is unchanged** — only its producer moves
from hand-written per-function helpers to one uniform handler.

### Preserved special cases
- **`parse_task_after_id`** (cursor): must keep tolerating both `task_<uuid>`
  and a bare uuid, and `None → None`. Implemented as a dedicated cursor parser
  (or `TaskId` construction, which already tolerates both) — not via the strict
  path-param route.
- **Removed/renamed prefixes** (e.g. `sesn_`) must still be rejected
  (`test_id_helper_error_contract.py:131`). `_coerce` rejects them because they
  don't match `cls.prefix` and the remainder isn't a valid uuid.

## Integration point 3 — SQLAlchemy TypeDecorator (ORM boundary)

```python
class EntityIdType(TypeDecorator):
    impl = UUID(as_uuid=True)
    cache_ok = True
    def __init__(self, id_cls): self.id_cls = id_cls; super().__init__()
    def process_bind_param(self, v, d):
        if v is None: return None
        return v.uuid if isinstance(v, EntityId) else self.id_cls(v).uuid
    def process_result_value(self, v, d):
        return None if v is None else self.id_cls(v)
```

Models declare typed PKs and FKs; the underlying column stays `UUID`:

```python
class JoySafeterTask(JoySafeterBaseModel):
    id: Mapped[TaskId] = mapped_column(EntityIdType(TaskId), primary_key=True, default=TaskId.new)
    agent_id: Mapped[AgentId] = mapped_column(EntityIdType(AgentId), ForeignKey("joysafeter_agents.id"))
    chat_session_id: Mapped[SessionId | None] = mapped_column(EntityIdType(SessionId), ForeignKey("joysafeter_sessions.id"), nullable=True)
    sandbox_id: Mapped[SandboxId | None] = mapped_column(EntityIdType(SandboxId), nullable=True)
    trigger_id: Mapped[TriggerId | None] = mapped_column(EntityIdType(TriggerId), ForeignKey("joysafeter_triggers.id", ondelete="SET NULL"), nullable=True)
```

- The `id` PK is **overridden per concrete model** (base `BaseModel.id` stays
  `uuid.UUID`; each entity redeclares `id` with its own `EntityIdType`).
- **No alembic migration** — the physical column type is unchanged (`UUID`).
- Indexes reference columns by **string name**, so they are unaffected.
- Domain services read typed ids straight off ORM attributes (`task.agent_id`
  is already an `AgentId`), which is what removes the `same_id` misuse.

## Integration point 4 — Remove `same_id` and inline scatter

- Delete `same_id` (`id_utils.py:7`). Replace all ~15 call sites (e.g.
  `agent_trigger_execution.py:143,159,262`, `task_submission_service.py:261,277`,
  `joysafeter_session_service.py:531`, `joysafeter_trigger_service.py:371`) with
  `==`. Both sides are typed ids → correct and statically safe.
- Delete `format_*` (`id_utils.py:18-31`); replace with `str(id)`.
- Fold `parse_event_id` into `EventId`.
- Absorb every **inline** prefix site into the appropriate `EntityId` subclass
  (see Inventory). No prefix literal survives outside `ids.py`.

## Authoritative prefix inventory

`ids.py` is the single source of truth. Registered UUID entities:

| Prefix       | Class                   | Current source(s) |
|--------------|-------------------------|-------------------|
| `agent_`     | `AgentId`               | id_helpers, id_utils, sessions.py:305, joysafeter_session.py:225 |
| `sess_`      | `SessionId`             | id_helpers, id_utils, files.py:59 |
| `task_`      | `TaskId`                | id_helpers, id_utils, `parse_task_after_id` |
| `env_`       | `EnvironmentId`         | id_helpers, environment_service.py:77, sessions.py:85 |
| `secret_`    | `SecretId`              | id_helpers |
| `trig_`      | `TriggerId`             | id_helpers |
| `memstore_`  | `MemoryStoreId`         | id_helpers |
| `mem_`       | `MemoryId`              | id_helpers |
| `memver_`    | `MemoryVersionId`       | id_helpers |
| `sbx_`       | `SandboxId`             | id_helpers, id_utils |
| `vault_`     | `VaultId`               | id_helpers, sessions.py:417 |
| `cred_`      | `CredentialId`          | id_helpers |
| `skill_`     | `SkillId`               | id_helpers, skill_service.py:930, agent_service.py:129, skills_ai_authoring.py:138 |
| `sklfile_`   | `SkillFileId`           | id_helpers |
| `sklscan_`   | `SkillSecurityScanId`   | id_helpers |
| `evt_`       | `EventId`               | id_utils.parse_event_id, session_service.py:34, sessions.py:2048 |
| `file_`      | `FileId`                | files.py:35, session_resource_service.py:584 |
| `sesrsc_`    | `SessionResourceId`     | session_resource_service.py:600 |

**Implementation must sweep** for any prefix literal not in this table before
finalizing (grep `removeprefix(`, `startswith("..._")`, `f"..._{`).

## Testing

- **`test_id_helper_error_contract.py`** is rewritten to assert the same payload
  shape from the **unified validation exit** (input moves from calling
  `parse_agent_id(...)` directly to driving request validation). External shape
  (`code`/`message`/`data`/`source`/`retryable`/`user_action`) is unchanged.
- New unit tests on `EntityId`: prefix round-trip (`str(AgentId(u))`),
  cross-type inequality (`AgentId(u) != SessionId(u)`), cross-entity
  construction raises `TypeError`, bare-uuid and prefixed-string coercion,
  rejection of wrong/removed prefixes.
- New tests on `EntityIdType`: bind (typed → uuid) and result (uuid → typed)
  round-trip.
- Existing contract tests that assert canonical serialized prefixes
  (`analytics`, `SandboxResponse`, `NetworkPolicyStatusResponse`, `FileResponse`)
  must stay green.
- Run from `backend/`: `cd backend && uv run pytest`.

## Rollout constraint

Must land **coherently** — you cannot type only half the graph, because the
`same_id → ==` replacement silently returns `False` where a typed side meets a
bare-uuid side. Delivery batching (which entities/PRs in what order) is decided
in the implementation plan, but each landed increment must leave no mixed
typed/bare comparison.

## Files touched (high level)

- **New:** `joysafeter_shared/ids.py` (value objects + `EntityIdType` + pydantic
  schema), global validation-error handler wiring in `joysafeter_api/app.py`.
- **Shrunk/removed:** `id_utils.py` (`same_id`, `format_*`, `parse_event_id`),
  `id_helpers.py` (`parse_*`, `_invalid_id_error`).
- **Edited:** all `models/*.py` (typed PK/FK columns), all schemas with id fields
  (drop `field_serializer`, type fields), all services with `same_id`/inline
  prefix handling, API routers using `parse_*` path deps.
```
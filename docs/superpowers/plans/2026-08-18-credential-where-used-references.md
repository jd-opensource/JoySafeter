# Credential Where-Used References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the vague `CREDENTIAL_IN_USE` archive/delete error into a proactive, layered, navigable "who uses this credential / in which flow" view, shared as the foundation for both this initiative and the service-credential create-flow redesign.

**Architecture:** Reuse the existing `dependency_scanners.py` scanner registry (produces name-free `CredentialDependency` domain objects tagged with `surface_id` + `source_id` + `dispositions`). Add a pure application-layer **reference-view assembler** that filters to blocking deps, maps the 4 live surfaces to a navigable `resource_type`, folds unmapped blockers into an `other_count`, and merges in batch-resolved names. Expose it via two read-only GET endpoints and reuse it to enrich the coordinator's 409 payload. The frontend renders one variant-aware `<CredentialReferences>` component on detail pages and inside archive/delete confirm dialogs.

**Tech Stack:** Python (FastAPI, SQLAlchemy async, pytest), TypeScript/React (Next.js, TanStack Query, vitest), i18n via `frontend/lib/i18n/locales/{en,zh}.ts`.

## Global Constraints

- Backend tests run from `backend/` only: `cd backend && uv run pytest` (never bare `pytest` at repo root — config lives in `backend/pyproject.toml`).
- Frontend tests run from `frontend/`: `cd frontend && npx vitest run <path>`.
- **Do NOT touch `.deps/SkillSpector`.**
- **The scanner/coordinator backend (`dependency_scanners.py`, `lifecycle_coordinator.py`, `composition.py`, `ports.py`, `sqlalchemy_repository.py`) is being live-edited in the working tree. Re-Read every backend integration file immediately before editing it; expect and tolerate "File has been modified since read" — re-read, don't retry blindly. If your intended change is already present, STOP and skip it.**
- **Commit by explicit file path only** (`git add <file1> <file2>`), never `git add -A`/`.` — the working tree carries concurrent uncommitted work.
- No new error code (reuse existing `CREDENTIAL_IN_USE`, registered at `backend/app/joysafeter_shared/common/error_catalog.py:52`) → no error-catalog guard change.
- No DB migration (only reads existing columns: `agent.name`, `trigger.name`, `environment.name`, `session.title`) → keep alembic single-head.
- Backend stays i18n-agnostic: return stable machine `surface` codes; the frontend localizes them.
- Consumer surfaces are exactly **agents / triggers / environments / sessions**. Skills are NOT a tracked surface — never render "skill" consumers.
- Spec: `docs/superpowers/specs/2026-08-18-credential-where-used-references-design.md` (rev3).

---

## File Structure

**Backend (create):**
- `backend/app/joysafeter_application/credentials/reference_view.py` — pure assembler: `ReferenceItem`, `ReferenceView`, `SURFACE_TO_TYPE`, `build_reference_view(...)`.
- `backend/tests/test_credential_reference_view.py` — assembler unit tests.
- `backend/tests/test_credential_references_endpoint.py` — endpoint + coordinator-409 integration tests.

**Backend (modify):**
- `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py` — add `names_for(resource_type, ids, project_id)`.
- `backend/app/joysafeter_domain/services/joysafeter_credential_service.py` — add `resource_reference_view(...)` / `group_reference_view(...)`.
- `backend/app/joysafeter_api/api/v1/credentials.py` — add `GET /{credential_id}/references` + response models.
- `backend/app/joysafeter_api/api/v1/credential_groups.py` — add `GET /{group_id}/references`.
- `backend/app/joysafeter_application/credentials/lifecycle_coordinator.py` — enrich `_observe_resource`/`_observe_group` 409 `data` with `references` + `other_count`.

**Frontend (create):**
- `frontend/hooks/managed/use-credential-references.ts` — `useCredentialReferences` / `useCredentialGroupReferences` + types + parser.
- `frontend/components/managed/credentials/credential-references.tsx` — `<CredentialReferences variant>`.
- `frontend/components/managed/credentials/credential-references.test.tsx` — component test.

**Frontend (modify):**
- `frontend/lib/i18n/locales/en.ts`, `frontend/lib/i18n/locales/zh.ts` — new i18n keys.
- `frontend/lib/managed/errors.ts` — `CREDENTIAL_IN_USE` fallback branch.
- `frontend/components/managed/credentials/model-connection-detail.tsx` — mount panel + gate confirm dialog.
- `frontend/components/managed/credentials/service-credential-detail.tsx` — mount panel + gate confirm dialog.
- `frontend/components/managed/credentials/mcp-vault-detail.tsx` — mount panel (group).
- `frontend/lib/i18n/credential-terminology.test.ts` — bump `sourceFileCount` by the number of new frontend source files added (2: the hook + the component; the `.test.tsx` is excluded from the count).

---

## Task 1: Reference-view assembler (pure)

**Files:**
- Create: `backend/app/joysafeter_application/credentials/reference_view.py`
- Test: `backend/tests/test_credential_reference_view.py`

**Interfaces:**
- Consumes: `CredentialDependency` from `app.joysafeter_domain.credentials.dependencies` (fields `surface_id: str`, `source_id: str`, `dispositions: frozenset[DependencyDisposition]`, method `blocks(disposition) -> bool`); `DependencyDisposition` enum.
- Produces:
  - `ReferenceItem(surface: str, resource_type: str, id: str, name: str | None)` (frozen dataclass)
  - `ReferenceView(references: list[ReferenceItem], other_count: int, can_archive: bool, can_delete: bool)` (frozen dataclass)
  - `SURFACE_TO_TYPE: dict[str, tuple[str, str]]` mapping `surface_id -> (resource_type, frontend_surface)`
  - `mappable_targets(deps, *, archive_disp, delete_disp) -> list[tuple[str, str]]` returning unique `(resource_type, source_id)` pairs needing name resolution
  - `build_reference_view(deps, names, *, archive_disp, delete_disp) -> ReferenceView` where `names: dict[tuple[str, str], str | None]` keyed by `(resource_type, source_id)`
  - `resolve_reference_view(deps, name_lookup, *, archive_disp, delete_disp) -> ReferenceView` — async helper shared by Task 3 (service) and Task 6 (coordinator) so the name-resolution loop is written ONCE. `name_lookup` is an async callable `(resource_type: str, ids: list[str]) -> dict[str, str | None]` (the caller binds `project_id`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_credential_reference_view.py
from app.joysafeter_application.credentials.reference_view import (
    ReferenceItem,
    build_reference_view,
    mappable_targets,
)
from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
)

ARCHIVE = DependencyDisposition.BLOCK_RESOURCE_ARCHIVE
DELETE = DependencyDisposition.BLOCK_RESOURCE_DELETE
BLOCK_RESOURCE = frozenset({ARCHIVE, DELETE})
PROJECT = "project-a"
CRED = "cred-1"


def _dep(surface_id: str, source_id: str, dispositions=BLOCK_RESOURCE) -> CredentialDependency:
    return CredentialDependency(
        surface_id=surface_id,
        project_id=PROJECT,
        source_id=source_id,
        credential_id=CRED,
        group_id=None,
        dispositions=dispositions,
    )


def test_maps_four_live_surfaces_with_names():
    deps = [
        _dep("live_agent_model_binding", "agent-1"),
        _dep("trigger_webhook_auth_binding", "trigger-1"),
        _dep("live_environment_direct_injection", "env-1"),
        _dep("active_session_model_environment_snapshot", "session-1"),
    ]
    targets = mappable_targets(deps, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert set(targets) == {
        ("agent", "agent-1"),
        ("trigger", "trigger-1"),
        ("environment", "env-1"),
        ("session", "session-1"),
    }
    names = {
        ("agent", "agent-1"): "客服机器人",
        ("trigger", "trigger-1"): "GitHub Hook",
        ("environment", "env-1"): "prod",
        ("session", "session-1"): None,
    }
    view = build_reference_view(deps, names, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert ReferenceItem("agent_model_binding", "agent", "agent-1", "客服机器人") in view.references
    assert ReferenceItem("active_session_snapshot", "session", "session-1", None) in view.references
    assert view.other_count == 0
    assert view.can_archive is False
    assert view.can_delete is False


def test_two_environment_surfaces_dedupe_same_id():
    deps = [
        _dep("live_environment_direct_injection", "env-1"),
        _dep("live_environment_http_egress_binding", "env-1"),
    ]
    view = build_reference_view(
        deps, {("environment", "env-1"): "prod"}, archive_disp=ARCHIVE, delete_disp=DELETE
    )
    env_items = [item for item in view.references if item.resource_type == "environment"]
    assert env_items == [ReferenceItem("environment_injection", "environment", "env-1", "prod")]


def test_unmapped_blocking_surface_folds_into_other_count():
    deps = [
        _dep("live_agent_model_binding", "agent-1"),
        _dep("legacy_v0_v1_environment_snapshot", "env-legacy"),
    ]
    view = build_reference_view(
        deps, {("agent", "agent-1"): "A"}, archive_disp=ARCHIVE, delete_disp=DELETE
    )
    assert [item.resource_type for item in view.references] == ["agent"]
    assert view.other_count == 1
    assert view.can_archive is False


def test_non_blocking_dep_excluded():
    deps = [
        _dep(
            "agent_version_executable_snapshot",
            "version-1",
            dispositions=frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
        ),
    ]
    view = build_reference_view(deps, {}, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert view.references == []
    assert view.other_count == 0
    assert view.can_archive is True
    assert view.can_delete is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_reference_view.py -q`
Expected: FAIL — `ModuleNotFoundError: ... reference_view`.

- [ ] **Step 3: Write the assembler**

```python
# backend/app/joysafeter_application/credentials/reference_view.py
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
)

# surface_id (scanner output) -> (resource_type, frontend surface code)
SURFACE_TO_TYPE: dict[str, tuple[str, str]] = {
    "live_agent_model_binding": ("agent", "agent_model_binding"),
    "trigger_webhook_auth_binding": ("trigger", "trigger_webhook_auth"),
    "live_environment_direct_injection": ("environment", "environment_injection"),
    "live_environment_http_egress_binding": ("environment", "environment_injection"),
    "active_session_model_environment_snapshot": ("session", "active_session_snapshot"),
    "session_credential_group_association": ("session", "active_session_snapshot"),
}


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    surface: str
    resource_type: str
    id: str
    name: str | None


@dataclass(frozen=True, slots=True)
class ReferenceView:
    references: list[ReferenceItem]
    other_count: int
    can_archive: bool
    can_delete: bool


def _blocking_deps(
    deps: Sequence[CredentialDependency],
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> list[CredentialDependency]:
    return [dep for dep in deps if dep.blocks(archive_disp) or dep.blocks(delete_disp)]


def mappable_targets(
    deps: Sequence[CredentialDependency],
    *,
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> list[tuple[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for dep in _blocking_deps(deps, archive_disp, delete_disp):
        mapping = SURFACE_TO_TYPE.get(str(dep.surface_id))
        if mapping is None:
            continue
        resource_type, _surface = mapping
        seen[(resource_type, str(dep.source_id))] = None
    return list(seen.keys())


def build_reference_view(
    deps: Sequence[CredentialDependency],
    names: dict[tuple[str, str], str | None],
    *,
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> ReferenceView:
    blocking = _blocking_deps(deps, archive_disp, delete_disp)
    references: list[ReferenceItem] = []
    emitted: set[tuple[str, str]] = set()
    other: set[tuple[str, str]] = set()
    for dep in blocking:
        surface_id = str(dep.surface_id)
        source_id = str(dep.source_id)
        mapping = SURFACE_TO_TYPE.get(surface_id)
        if mapping is None:
            other.add((surface_id, source_id))
            continue
        resource_type, surface = mapping
        key = (resource_type, source_id)
        if key in emitted:
            continue
        emitted.add(key)
        references.append(
            ReferenceItem(
                surface=surface,
                resource_type=resource_type,
                id=source_id,
                name=names.get(key),
            )
        )
    can_archive = not any(dep.blocks(archive_disp) for dep in deps)
    can_delete = not any(dep.blocks(delete_disp) for dep in deps)
    return ReferenceView(
        references=references,
        other_count=len(other),
        can_archive=can_archive,
        can_delete=can_delete,
    )


async def resolve_reference_view(
    deps: Sequence[CredentialDependency],
    name_lookup,
    *,
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> ReferenceView:
    """Resolve names for the mappable blocking deps and build the view.

    ``name_lookup`` is an async callable ``(resource_type, ids) -> {id: name}``;
    the caller binds ``project_id``. Written once here so the service (Task 3)
    and the coordinator (Task 6) share one name-resolution path.
    """
    targets = mappable_targets(deps, archive_disp=archive_disp, delete_disp=delete_disp)
    by_type: dict[str, list[str]] = {}
    for resource_type, source_id in targets:
        by_type.setdefault(resource_type, []).append(source_id)
    names: dict[tuple[str, str], str | None] = {}
    for resource_type, ids in by_type.items():
        resolved = await name_lookup(resource_type, ids)
        for source_id in ids:
            names[(resource_type, source_id)] = resolved.get(str(source_id))
    return build_reference_view(deps, names, archive_disp=archive_disp, delete_disp=delete_disp)
```

Add an async test for the shared helper to `test_credential_reference_view.py` (uses a fake `name_lookup`, no DB):

```python
import pytest

from app.joysafeter_application.credentials.reference_view import resolve_reference_view


@pytest.mark.asyncio
async def test_resolve_reference_view_uses_name_lookup():
    deps = [_dep("live_agent_model_binding", "agent-1")]

    async def fake_lookup(resource_type, ids):
        assert resource_type == "agent"
        return {"agent-1": "客服机器人"}

    view = await resolve_reference_view(deps, fake_lookup, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert view.references == [ReferenceItem("agent_model_binding", "agent", "agent-1", "客服机器人")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_reference_view.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_application/credentials/reference_view.py backend/tests/test_credential_reference_view.py
git commit -m "feat(credentials): pure reference-view assembler for where-used"
```

---

## Task 2: Name-resolution on the repository

**Files:**
- Modify: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Test: `backend/tests/test_credential_references_endpoint.py` (new file; first test only)

**Interfaces:**
- Produces: `SqlAlchemyCredentialRepository.names_for(resource_type: str, ids: Sequence[str], project_id: str) -> dict[str, str | None]` — batch id→name for one resource type, filtered by project. `resource_type in {"agent","trigger","environment","session"}`; unknown type returns `{}`. Sessions map from `title` (nullable).

**Note:** Re-Read `sqlalchemy_repository.py` before editing (live-edited). Add the method on the `SqlAlchemyCredentialRepository` class near the existing `dependencies(...)` scan.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_credential_references_endpoint.py
import pytest

from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import (
    SqlAlchemyCredentialRepository,
)


@pytest.mark.asyncio
async def test_names_for_resolves_agent_names(db_session, seeded_agent):
    # seeded_agent fixture: creates an agent id=<agent_id>, name="客服机器人", project="project-a"
    repo = SqlAlchemyCredentialRepository(db_session, material=None)
    names = await repo.names_for("agent", [seeded_agent.id], project_id="project-a")
    assert names == {str(seeded_agent.id): "客服机器人"}


@pytest.mark.asyncio
async def test_names_for_unknown_type_returns_empty(db_session):
    repo = SqlAlchemyCredentialRepository(db_session, material=None)
    assert await repo.names_for("nope", ["x"], project_id="project-a") == {}


@pytest.mark.asyncio
async def test_names_for_empty_ids_returns_empty(db_session):
    repo = SqlAlchemyCredentialRepository(db_session, material=None)
    assert await repo.names_for("agent", [], project_id="project-a") == {}
```

> If a `seeded_agent` fixture does not already exist in `backend/tests/conftest.py`, add a minimal one that inserts a `JoySafeterAgent(project_id="project-a", name="客服机器人", ...)` mirroring existing agent-seeding fixtures in the suite (search `tests/` for `JoySafeterAgent(` to copy required columns). Fold that fixture addition into this task.
>
> **Repository construction:** `SqlAlchemyCredentialRepository(db, material=...)` may require a real `material` adapter. If `material=None` fails at construction, obtain the repository via the app composition instead: `from app.joysafeter_application.credentials.composition import compose_credential_application; repo = compose_credential_application(db_session, compatibility_mode=False).uow.credentials`. `names_for` does not use `material`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'names_for'`.

- [ ] **Step 3: Implement `names_for`**

Add to `SqlAlchemyCredentialRepository` (import the models at module top or inside the method as the file's existing scan does):

```python
    async def names_for(
        self,
        resource_type: str,
        ids: Sequence[str],
        project_id: str,
    ) -> dict[str, str | None]:
        if not ids:
            return {}
        from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
        from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
        from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger

        table_column = {
            "agent": (JoySafeterAgent, JoySafeterAgent.name),
            "trigger": (JoySafeterTrigger, JoySafeterTrigger.name),
            "environment": (JoySafeterEnvironment, JoySafeterEnvironment.name),
            "session": (JoySafeterSession, JoySafeterSession.title),
        }.get(resource_type)
        if table_column is None:
            return {}
        model, name_col = table_column
        rows = await self.db.execute(
            select(model.id, name_col).where(
                model.id.in_(list(ids)),
                model.project_id == project_id,
            )
        )
        return {str(row_id): value for row_id, value in rows.all()}
```

> Ensure `from collections.abc import Sequence` is imported at the top of the file (add if missing). `select` is already imported in this module.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py backend/tests/test_credential_references_endpoint.py backend/tests/conftest.py
git commit -m "feat(credentials): batch name resolution for reference view"
```

---

## Task 3: Credential-service reference-view methods

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_service.py`
- Test: `backend/tests/test_credential_references_endpoint.py` (add tests)

**Interfaces:**
- Consumes: `CredentialService._application.scan_resource_dependencies(project_id, credential_id)` and `.scan_group_dependencies(project_id, group_id)` (both return `Sequence[CredentialDependency]`, defined in `composition.py`); `CredentialService._application.uow.credentials.names_for(...)` (Task 2); `build_reference_view` / `mappable_targets` / `SURFACE_TO_TYPE` (Task 1); `DependencyDisposition`.
- Produces:
  - `CredentialService.resource_reference_view(credential_id, project_id) -> ReferenceView`
  - `CredentialService.group_reference_view(group_id, project_id) -> ReferenceView`

**Note:** Re-Read `joysafeter_credential_service.py` before editing (live-edited).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_credential_references_endpoint.py
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService


@pytest.mark.asyncio
async def test_resource_reference_view_names_a_binding_agent(
    db_session, seeded_agent_bound_to_credential
):
    # fixture: agent (name="客服机器人") whose model_credential_id = <cred_id>, project "project-a"
    cred_id = seeded_agent_bound_to_credential.credential_id
    svc = CredentialService(db_session, compatibility_mode=False)
    view = await svc.resource_reference_view(cred_id, project_id="project-a")
    assert view.can_archive is False
    agent_items = [item for item in view.references if item.resource_type == "agent"]
    assert agent_items and agent_items[0].name == "客服机器人"
    assert agent_items[0].surface == "agent_model_binding"


@pytest.mark.asyncio
async def test_resource_reference_view_clean_credential(db_session, seeded_unused_credential):
    svc = CredentialService(db_session, compatibility_mode=False)
    view = await svc.resource_reference_view(
        seeded_unused_credential.id, project_id="project-a"
    )
    assert view.references == []
    assert view.other_count == 0
    assert view.can_archive is True
    assert view.can_delete is True
```

> Reuse or extend existing credential/agent seeding fixtures. If `seeded_agent_bound_to_credential` / `seeded_unused_credential` don't exist, add minimal fixtures in `conftest.py` that create a service/model credential and (for the bound case) an agent with `model_credential_id` set. Search `tests/` for existing credential-creation helpers to copy the required insert shape.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k reference_view`
Expected: FAIL — `AttributeError: 'CredentialService' object has no attribute 'resource_reference_view'`.

- [ ] **Step 3: Implement the service methods**

Add to `CredentialService` (imports at top of file):

```python
from app.joysafeter_application.credentials.reference_view import (
    ReferenceView,
    resolve_reference_view,
)
```

```python
    async def _reference_view(
        self,
        deps,
        project_id: str,
        *,
        archive_disp: DependencyDisposition,
        delete_disp: DependencyDisposition,
    ) -> ReferenceView:
        repo = self._application.uow.credentials

        async def name_lookup(resource_type, ids):
            return await repo.names_for(resource_type, ids, project_id=str(project_id))

        return await resolve_reference_view(
            deps, name_lookup, archive_disp=archive_disp, delete_disp=delete_disp
        )

    async def resource_reference_view(self, credential_id, project_id: str) -> ReferenceView:
        deps = await self._application.scan_resource_dependencies(
            str(project_id), str(credential_id)
        )
        return await self._reference_view(
            deps,
            project_id,
            archive_disp=DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
            delete_disp=DependencyDisposition.BLOCK_RESOURCE_DELETE,
        )

    async def group_reference_view(self, group_id, project_id: str) -> ReferenceView:
        deps = await self._application.scan_group_dependencies(str(project_id), str(group_id))
        return await self._reference_view(
            deps,
            project_id,
            archive_disp=DependencyDisposition.BLOCK_GROUP_ARCHIVE,
            delete_disp=DependencyDisposition.BLOCK_GROUP_DELETE,
        )
```

> `DependencyDisposition` is already imported in this file (used by `_observe_dependency_registry`). If not, add `from app.joysafeter_domain.credentials.dependencies import DependencyDisposition`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k reference_view`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_credential_service.py backend/tests/test_credential_references_endpoint.py backend/tests/conftest.py
git commit -m "feat(credentials): service-level resource/group reference views"
```

---

## Task 4: `GET /credentials/{id}/references` endpoint

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Test: `backend/tests/test_credential_references_endpoint.py` (add API test)

**Interfaces:**
- Consumes: `CredentialService.resource_reference_view(...)` (Task 3); existing route deps `get_db`, `require_joysafeter_write`/read equivalent, `CredentialId` path type (mirror the existing `archive_credential` handler at `credentials.py:424`).
- Produces: `GET /api/v1/credentials/{credential_id}/references` → JSON `{"references": [{"surface","resource_type","id","name"}], "other_count": int, "can_archive": bool, "can_delete": bool}`.

**Note:** Re-Read `credentials.py` before editing. Use the same auth dependency the sibling GET handlers use (read scope). Check the file's existing `Depends(...)` for the read-auth symbol (e.g. `require_joysafeter_read`); reuse it.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_credential_references_endpoint.py
@pytest.mark.asyncio
async def test_get_credential_references_endpoint(async_client, seeded_agent_bound_to_credential):
    cred_id = seeded_agent_bound_to_credential.credential_id
    resp = await async_client.get(f"/api/v1/credentials/{cred_id}/references")
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_archive"] is False
    assert body["other_count"] == 0
    agents = [r for r in body["references"] if r["resource_type"] == "agent"]
    assert agents and agents[0]["name"] == "客服机器人"
    assert agents[0]["surface"] == "agent_model_binding"
```

> Use whatever authenticated async client fixture the existing `credentials.py` endpoint tests use (search `backend/tests/` for `/api/v1/credentials/` GET tests to copy the client + auth-header fixture).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k endpoint`
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Implement the endpoint**

Add Pydantic response models near the top of `credentials.py` (after existing imports/models):

```python
from pydantic import BaseModel


class CredentialReferenceItemResponse(BaseModel):
    surface: str
    resource_type: str
    id: str
    name: str | None


class CredentialReferencesResponse(BaseModel):
    references: list[CredentialReferenceItemResponse]
    other_count: int
    can_archive: bool
    can_delete: bool
```

Add the handler (mirror the read-auth dep used by other GET routes in this file):

```python
@router.get("/{credential_id}/references", response_model=CredentialReferencesResponse)
async def get_credential_references(
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_read),
) -> CredentialReferencesResponse:
    svc = CredentialService(db, compatibility_mode=False)
    view = await svc.resource_reference_view(credential_id, project_id=auth_ctx.project_id)
    return CredentialReferencesResponse(
        references=[
            CredentialReferenceItemResponse(
                surface=item.surface,
                resource_type=item.resource_type,
                id=item.id,
                name=item.name,
            )
            for item in view.references
        ],
        other_count=view.other_count,
        can_archive=view.can_archive,
        can_delete=view.can_delete,
    )
```

> If `require_joysafeter_read` is not the read-auth symbol in this file, use the one the file already imports for GET handlers. `BaseModel` may already be imported — don't duplicate.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k endpoint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_api/api/v1/credentials.py backend/tests/test_credential_references_endpoint.py
git commit -m "feat(credentials): GET /credentials/{id}/references endpoint"
```

---

## Task 5: `GET /credential-groups/{id}/references` endpoint

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/credential_groups.py`
- Test: `backend/tests/test_credential_references_endpoint.py` (add group test)

**Interfaces:**
- Consumes: `CredentialService.group_reference_view(...)` (Task 3); the response models from Task 4 — import them from `credentials.py` (`from app.joysafeter_api.api.v1.credentials import CredentialReferencesResponse, CredentialReferenceItemResponse`) to avoid duplication.
- Produces: `GET /api/v1/credential-groups/{group_id}/references` → same JSON shape as Task 4 (group blockers are `active_session_snapshot`).

**Note:** Re-Read `credential_groups.py` before editing. Mirror the existing `GET /{group_id}` handler (`credential_groups.py:111`) for auth + path-type conventions.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_credential_references_endpoint.py
@pytest.mark.asyncio
async def test_get_group_references_endpoint(async_client, seeded_group_bound_to_session):
    group_id = seeded_group_bound_to_session.group_id
    resp = await async_client.get(f"/api/v1/credential-groups/{group_id}/references")
    assert resp.status_code == 200
    body = resp.json()
    sessions = [r for r in body["references"] if r["resource_type"] == "session"]
    assert sessions and sessions[0]["surface"] == "active_session_snapshot"
    assert body["can_archive"] is False
```

> Add a `seeded_group_bound_to_session` fixture if absent: a credential group with an active `JoySafeterSessionCredentialGroup` association to a non-terminated session (copy the association shape from `dependency_scanners.py` `SessionCredentialGroupAssociationScanner` query and existing group tests).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k group_references`
Expected: FAIL — 404.

- [ ] **Step 3: Implement the endpoint**

```python
from app.joysafeter_api.api.v1.credentials import (
    CredentialReferenceItemResponse,
    CredentialReferencesResponse,
)


@router.get("/{group_id}/references", response_model=CredentialReferencesResponse)
async def get_group_references(
    group_id: CredentialGroupId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_read),
) -> CredentialReferencesResponse:
    svc = CredentialService(db, compatibility_mode=False)
    view = await svc.group_reference_view(group_id, project_id=auth_ctx.project_id)
    return CredentialReferencesResponse(
        references=[
            CredentialReferenceItemResponse(
                surface=item.surface,
                resource_type=item.resource_type,
                id=item.id,
                name=item.name,
            )
            for item in view.references
        ],
        other_count=view.other_count,
        can_archive=view.can_archive,
        can_delete=view.can_delete,
    )
```

> Use the `CredentialGroupId` path type and read-auth symbol already imported in `credential_groups.py`. If a circular-import arises importing from `credentials.py`, instead move the two response models into a small shared module `backend/app/joysafeter_api/api/v1/credential_reference_models.py` and import from there in both routers (fold that move into this task).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k group_references`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_api/api/v1/credential_groups.py backend/tests/test_credential_references_endpoint.py
git commit -m "feat(credentials): GET /credential-groups/{id}/references endpoint"
```

---

## Task 6: Enrich the coordinator 409 payload

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/lifecycle_coordinator.py`
- Test: `backend/tests/test_credential_references_endpoint.py` (add 409-shape test)

**Interfaces:**
- Consumes: the same `_scan_resource_dependencies` / `_scan_group_dependencies` already held by the coordinator; `build_reference_view` / `mappable_targets` (Task 1); the uow's `credentials.names_for` (Task 2, reachable via `self._uow.credentials.names_for`).
- Produces: on `enforce`-mode block, `CREDENTIAL_IN_USE` `data` gains `references: [...]` and `other_count: int` (keep existing `dependency_ids`/`dependency_count` for telemetry).

**Note:** Re-Read `lifecycle_coordinator.py` before editing — `_observe_resource` (~`:95`) and `_observe_group` (~`:177`) are live-edited. Only change the `raise ResourceConflictError(...)` `data=` blocks in the `blockers:` branches; leave the shadow-mode diff logging untouched.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_credential_references_endpoint.py
@pytest.mark.asyncio
async def test_archive_409_carries_named_references(
    async_client, seeded_agent_bound_to_credential, enforce_dependency_registry
):
    # enforce_dependency_registry fixture: set settings.credential_dependency_registry_mode="enforce"
    cred_id = seeded_agent_bound_to_credential.credential_id
    resp = await async_client.post(f"/api/v1/credentials/{cred_id}/archive")
    assert resp.status_code == 409
    data = resp.json()
    envelope = data.get("data") or data
    assert envelope["references"][0]["resource_type"] == "agent"
    assert envelope["references"][0]["name"] == "客服机器人"
    assert "other_count" in envelope
```

> Add an `enforce_dependency_registry` fixture that monkeypatches `settings.credential_dependency_registry_mode = "enforce"` for the test (search for how existing tests set that setting; there is shadow/enforce handling already). The exact JSON envelope location (top-level vs nested `data`) — mirror how existing `CREDENTIAL_IN_USE`/409 tests read the body.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k 409`
Expected: FAIL — `KeyError: 'references'` (old payload only has `dependency_ids`).

- [ ] **Step 3: Add a shared enrichment helper and use it in both raise sites**

Add a coordinator method:

```python
    async def _reference_payload(
        self,
        deps,
        project_id: str,
        *,
        archive_disp: DependencyDisposition,
        delete_disp: DependencyDisposition,
    ) -> dict:
        from app.joysafeter_application.credentials.reference_view import resolve_reference_view

        async def name_lookup(resource_type, ids):
            return await self._uow.credentials.names_for(
                resource_type, ids, project_id=str(project_id)
            )

        view = await resolve_reference_view(
            deps, name_lookup, archive_disp=archive_disp, delete_disp=delete_disp
        )
        return {
            "references": [
                {
                    "surface": item.surface,
                    "resource_type": item.resource_type,
                    "id": item.id,
                    "name": item.name,
                }
                for item in view.references
            ],
            "other_count": view.other_count,
        }
```

In `_observe_resource`, the `if blockers:` branch — replace the `data=` block:

```python
        if blockers:
            payload = await self._reference_payload(
                new_dependencies,
                project_id,
                archive_disp=DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
                delete_disp=DependencyDisposition.BLOCK_RESOURCE_DELETE,
            )
            raise ResourceConflictError(
                code="CREDENTIAL_IN_USE",
                message="Credential is still referenced and cannot be changed",
                data={
                    "credential_id": str(credential_id),
                    "dependency_ids": blockers,
                    "dependency_count": len(blockers),
                    "dispositions": new_dispositions,
                    **payload,
                },
                user_action="fix_input",
            )
```

In `_observe_group`, the `if blockers:` branch — replace the `data=` block:

```python
        if blockers:
            payload = await self._reference_payload(
                dependencies,
                project_id,
                archive_disp=DependencyDisposition.BLOCK_GROUP_ARCHIVE,
                delete_disp=DependencyDisposition.BLOCK_GROUP_DELETE,
            )
            raise ResourceConflictError(
                code="CREDENTIAL_IN_USE",
                message="Credential group is still referenced and cannot be changed",
                data={
                    "credential_group_id": str(group_id),
                    "dependency_ids": blockers,
                    "dependency_count": len(blockers),
                    "dispositions": [disposition.value],
                    **payload,
                },
                user_action="fix_input",
            )
```

> `new_dependencies` (resource) and `dependencies` (group) are the already-scanned `CredentialDependency` tuples in scope at each raise site — reuse them; do NOT re-scan.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_references_endpoint.py -q -k 409`
Expected: PASS.

- [ ] **Step 5: Run the full credential suite for regressions, then commit**

Run: `cd backend && uv run pytest tests/ -q -k credential`
Expected: PASS (no regressions in existing `_observe_*` / dependency tests).

```bash
git add backend/app/joysafeter_application/credentials/lifecycle_coordinator.py backend/tests/test_credential_references_endpoint.py
git commit -m "feat(credentials): enrich CREDENTIAL_IN_USE 409 with named references"
```

---

## Task 7: Frontend hook + types

**Files:**
- Create: `frontend/hooks/managed/use-credential-references.ts`

**Interfaces:**
- Consumes: `managedGet` from `@/lib/api-client`; `apiResourcePath` from `@/lib/managed/api-paths`; `useManagedRequestScope`, `managedRequestOptions`, `hasManagedRequestScope` from `@/lib/managed/request-scope`; `useQuery` from `@tanstack/react-query`.
- Produces:
  - types `CredentialReferenceItem { surface: string; resourceType: 'agent'|'trigger'|'environment'|'session'; id: string; name: string | null }`, `CredentialReferences { references: CredentialReferenceItem[]; otherCount: number; canArchive: boolean; canDelete: boolean }`
  - `parseReferencesResponse(raw: unknown): CredentialReferences`
  - `useCredentialReferences(id: string, opts?: { enabled?: boolean })`
  - `useCredentialGroupReferences(id: string, opts?: { enabled?: boolean })`

**Note:** Confirm `apiResourcePath('credentials', id, 'references')` produces `/credentials/{id}/references` (it's the same helper used at `model-connection-detail.tsx:127` for `('credentials', id, 'default')`). For groups, verify the collection segment (`'credential-groups'` vs `'credential_groups'`) by checking an existing group call in the frontend before finalizing.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/hooks/managed/use-credential-references.test.tsx
import { parseReferencesResponse } from './use-credential-references'

describe('parseReferencesResponse', () => {
  it('maps snake_case payload to typed camelCase', () => {
    const parsed = parseReferencesResponse({
      references: [
        { surface: 'agent_model_binding', resource_type: 'agent', id: 'a1', name: '客服机器人' },
        { surface: 'active_session_snapshot', resource_type: 'session', id: 's1', name: null },
      ],
      other_count: 2,
      can_archive: false,
      can_delete: false,
    })
    expect(parsed.references).toHaveLength(2)
    expect(parsed.references[0]).toEqual({
      surface: 'agent_model_binding',
      resourceType: 'agent',
      id: 'a1',
      name: '客服机器人',
    })
    expect(parsed.otherCount).toBe(2)
    expect(parsed.canArchive).toBe(false)
  })

  it('defaults gracefully on empty/missing fields', () => {
    const parsed = parseReferencesResponse({})
    expect(parsed.references).toEqual([])
    expect(parsed.otherCount).toBe(0)
    expect(parsed.canArchive).toBe(true)
    expect(parsed.canDelete).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run hooks/managed/use-credential-references.test.tsx`
Expected: FAIL — module/export not found.

- [ ] **Step 3: Implement the hook**

```ts
// frontend/hooks/managed/use-credential-references.ts
'use client'

import { useQuery } from '@tanstack/react-query'

import { managedGet } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

export type CredentialReferenceResourceType = 'agent' | 'trigger' | 'environment' | 'session'

export interface CredentialReferenceItem {
  surface: string
  resourceType: CredentialReferenceResourceType
  id: string
  name: string | null
}

export interface CredentialReferences {
  references: CredentialReferenceItem[]
  otherCount: number
  canArchive: boolean
  canDelete: boolean
}

export function parseReferencesResponse(raw: unknown): CredentialReferences {
  const obj = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const rawItems = Array.isArray(obj.references) ? obj.references : []
  const references: CredentialReferenceItem[] = rawItems.map((entry) => {
    const item = (entry && typeof entry === 'object' ? entry : {}) as Record<string, unknown>
    return {
      surface: typeof item.surface === 'string' ? item.surface : '',
      resourceType: item.resource_type as CredentialReferenceResourceType,
      id: typeof item.id === 'string' ? item.id : '',
      name: typeof item.name === 'string' ? item.name : null,
    }
  })
  return {
    references,
    otherCount: typeof obj.other_count === 'number' ? obj.other_count : 0,
    canArchive: obj.can_archive === undefined ? true : obj.can_archive === true,
    canDelete: obj.can_delete === undefined ? true : obj.can_delete === true,
  }
}

function useReferences(collection: 'credentials' | 'credential-groups', id: string, enabled: boolean) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['credential-references', collection, scope.key, id],
    queryFn: async () => {
      const raw = await managedGet<unknown>(
        apiResourcePath(collection, id, 'references'),
        managedRequestOptions(scope),
      )
      return parseReferencesResponse(raw)
    },
    enabled: enabled && !!id && hasManagedRequestScope(scope),
    staleTime: 15_000,
  })
}

export function useCredentialReferences(id: string, opts: { enabled?: boolean } = {}) {
  return useReferences('credentials', id, opts.enabled ?? true)
}

export function useCredentialGroupReferences(id: string, opts: { enabled?: boolean } = {}) {
  return useReferences('credential-groups', id, opts.enabled ?? true)
}
```

> Verify the `'credential-groups'` segment matches the real route prefix; if the frontend uses a different literal, use that. `apiResourcePath` signature must accept `(collection, id, subpath)` — confirm against `@/lib/managed/api-paths`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run hooks/managed/use-credential-references.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/managed/use-credential-references.ts frontend/hooks/managed/use-credential-references.test.tsx
git commit -m "feat(credentials): useCredentialReferences hook + response parser"
```

---

## Task 8: `<CredentialReferences>` component + i18n

**Files:**
- Create: `frontend/components/managed/credentials/credential-references.tsx`
- Create: `frontend/components/managed/credentials/credential-references.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`, `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/lib/i18n/credential-terminology.test.ts` (bump `sourceFileCount` by 2)

**Interfaces:**
- Consumes: `CredentialReferences`, `CredentialReferenceItem` types (Task 7); `useTranslation` (project i18n hook — copy import from a sibling component like `model-connection-detail.tsx`); Next.js `Link`.
- Produces: `<CredentialReferences data={CredentialReferences} variant="informational" | "blocker" />` — groups items by `surface`, renders a localized flow heading + count per group, each item a `<Link>` to its route; renders a non-clickable "N legacy refs" line when `otherCount > 0`; renders nothing when `references` empty and `otherCount === 0`.

**Route map** (item → href):
- `agent` → `/managed/agents/{id}`
- `trigger` → `/managed/triggers/{id}`
- `environment` → `/managed/environments/{id}`
- `session` → `/managed/sessions/{id}`

- [ ] **Step 1: Add i18n keys**

In `frontend/lib/i18n/locales/en.ts`, under the `managed.credentials` object add a `references` block:

```ts
references: {
  blockerTitle: 'In use at the following — unbind there first:',
  informationalTitle: 'Used at the following locations:',
  surfaceAgentModelBinding: 'Model binding',
  surfaceTriggerWebhookAuth: 'Webhook auth',
  surfaceEnvironmentInjection: 'Environment injection',
  surfaceActiveSessionSnapshot: 'Active session',
  sessionFallback: 'Session {{id}}',
  otherCount: '{{count}} more legacy snapshot reference(s) blocking',
},
```

Mirror in `frontend/lib/i18n/locales/zh.ts`:

```ts
references: {
  blockerTitle: '以下位置正在使用，请先解绑：',
  informationalTitle: '被使用于以下位置：',
  surfaceAgentModelBinding: '模型绑定',
  surfaceTriggerWebhookAuth: 'Webhook 鉴权',
  surfaceEnvironmentInjection: '环境注入',
  surfaceActiveSessionSnapshot: '活跃会话',
  sessionFallback: '会话 {{id}}',
  otherCount: '另有 {{count}} 处历史快照引用阻塞',
},
```

> Match the exact nesting/style the file uses (find `credentials:` in each locale). Keep key parity between en and zh — a terminology guard checks both locales.

- [ ] **Step 2: Write the failing component test**

```tsx
// frontend/components/managed/credentials/credential-references.test.tsx
import { render, screen } from '@testing-library/react'

import { CredentialReferences } from './credential-references'

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o?.id ?? o?.count ?? k) as string }),
}))

const base = {
  references: [
    { surface: 'agent_model_binding', resourceType: 'agent' as const, id: 'a1', name: '客服机器人' },
    { surface: 'active_session_snapshot', resourceType: 'session' as const, id: 's1', name: null },
  ],
  otherCount: 0,
  canArchive: false,
  canDelete: false,
}

describe('CredentialReferences', () => {
  it('renders each item as a link to its route', () => {
    render(<CredentialReferences data={base} variant="blocker" />)
    expect(screen.getByText('客服机器人').closest('a')).toHaveAttribute('href', '/managed/agents/a1')
    // session with null name → fallback shows the id
    expect(screen.getByText('s1').closest('a')).toHaveAttribute('href', '/managed/sessions/s1')
  })

  it('renders the legacy other-count line but not as a link', () => {
    render(<CredentialReferences data={{ ...base, otherCount: 3 }} variant="blocker" />)
    const other = screen.getByText('3')
    expect(other.closest('a')).toBeNull()
  })

  it('renders nothing when empty', () => {
    const { container } = render(
      <CredentialReferences
        data={{ references: [], otherCount: 0, canArchive: true, canDelete: true }}
        variant="informational"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run components/managed/credentials/credential-references.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the component**

```tsx
// frontend/components/managed/credentials/credential-references.tsx
'use client'

import Link from 'next/link'

import { useTranslation } from '@/lib/i18n'
import type {
  CredentialReferenceItem,
  CredentialReferenceResourceType,
  CredentialReferences as CredentialReferencesData,
} from '@/hooks/managed/use-credential-references'

const ROUTE: Record<CredentialReferenceResourceType, string> = {
  agent: '/managed/agents',
  trigger: '/managed/triggers',
  environment: '/managed/environments',
  session: '/managed/sessions',
}

const SURFACE_LABEL_KEY: Record<string, string> = {
  agent_model_binding: 'managed.credentials.references.surfaceAgentModelBinding',
  trigger_webhook_auth: 'managed.credentials.references.surfaceTriggerWebhookAuth',
  environment_injection: 'managed.credentials.references.surfaceEnvironmentInjection',
  active_session_snapshot: 'managed.credentials.references.surfaceActiveSessionSnapshot',
}

export function CredentialReferences({
  data,
  variant,
}: {
  data: CredentialReferencesData
  variant: 'informational' | 'blocker'
}) {
  const { t } = useTranslation()
  if (data.references.length === 0 && data.otherCount === 0) return null

  const groups = new Map<string, CredentialReferenceItem[]>()
  for (const item of data.references) {
    const list = groups.get(item.surface) ?? []
    list.push(item)
    groups.set(item.surface, list)
  }

  const titleKey =
    variant === 'blocker'
      ? 'managed.credentials.references.blockerTitle'
      : 'managed.credentials.references.informationalTitle'

  return (
    <div className="space-y-3 rounded-md border p-3 text-sm">
      <p className="font-medium">{t(titleKey)}</p>
      {[...groups.entries()].map(([surface, items]) => (
        <div key={surface} className="space-y-1">
          <p className="text-muted-foreground">
            {t(SURFACE_LABEL_KEY[surface] ?? surface)} · {items.length}
          </p>
          <ul className="space-y-0.5">
            {items.map((item) => (
              <li key={`${item.resourceType}:${item.id}`}>
                <Link className="text-primary hover:underline" href={`${ROUTE[item.resourceType]}/${item.id}`}>
                  {item.name ?? t('managed.credentials.references.sessionFallback', { id: item.id })}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {data.otherCount > 0 && (
        <p className="text-muted-foreground">
          {t('managed.credentials.references.otherCount', { count: data.otherCount })}
        </p>
      )}
    </div>
  )
}
```

> Confirm the `useTranslation` import path (`@/lib/i18n`) against a sibling component; adjust if the project uses a different module. The className tokens are illustrative — match existing components' styling utilities.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run components/managed/credentials/credential-references.test.tsx`
Expected: PASS.

- [ ] **Step 6: Bump the source-file inventory count**

Run: `cd frontend && npx vitest run lib/i18n/credential-terminology.test.ts`
Expected: FAIL on `sourceFileCount` `toBe(N)` (off by the number of new source files: the hook + the component = 2; `.test.tsx` files are excluded).
Then edit `frontend/lib/i18n/credential-terminology.test.ts` to bump `toBe(N)` → `toBe(N+2)` (only account for these 2 files; do not absorb others' uncommitted additions — if the delta is not exactly +2, investigate before changing).
Re-run: `cd frontend && npx vitest run lib/i18n/credential-terminology.test.ts` → PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/managed/credentials/credential-references.tsx frontend/components/managed/credentials/credential-references.test.tsx frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts frontend/lib/i18n/credential-terminology.test.ts
git commit -m "feat(credentials): CredentialReferences component + i18n"
```

---

## Task 9: `CREDENTIAL_IN_USE` error fallback

**Files:**
- Modify: `frontend/lib/managed/errors.ts`
- Test: `frontend/lib/managed/errors.test.ts` (create if absent, else append)

**Interfaces:**
- Consumes: existing `parseApiError` + `getOperationErrorMessage(t, error, fallbackKey)` in `errors.ts:59`.
- Produces: a `CREDENTIAL_IN_USE` branch in `getOperationErrorMessage` that produces a concise summary string from `data` — handling BOTH the new shape (`data.references` with names) and the legacy shapes (`data.dependency_ids` / `data.agents/triggers/environments/sessions`), never falling through to a bare English message.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/managed/errors.test.ts (append if file exists)
import { getOperationErrorMessage } from './errors'

const t = (k: string, o?: Record<string, unknown>) =>
  o ? `${k}:${JSON.stringify(o)}` : k

describe('getOperationErrorMessage CREDENTIAL_IN_USE', () => {
  it('summarizes the new references shape', () => {
    const msg = getOperationErrorMessage(
      t,
      { code: 'CREDENTIAL_IN_USE', message: 'x', data: { references: [{ resource_type: 'agent', name: 'A' }], other_count: 0 } },
      'common.operationFailed',
    )
    expect(msg).toContain('managed.credentials.references.inUseSummary')
  })

  it('summarizes the legacy dependency_ids shape', () => {
    const msg = getOperationErrorMessage(
      t,
      { code: 'CREDENTIAL_IN_USE', message: 'x', data: { dependency_ids: ['a', 'b'] } },
      'common.operationFailed',
    )
    expect(msg).toContain('managed.credentials.references.inUseSummary')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run lib/managed/errors.test.ts`
Expected: FAIL — message falls through to raw `'x'`.

- [ ] **Step 3: Add the summary i18n key + the branch**

Add to both locales under `managed.credentials.references`:

```ts
inUseSummary: 'Still referenced by {{count}} item(s). Resolve them before archiving or deleting.',
```
```ts
inUseSummary: '仍被 {{count}} 处引用，请先解绑再归档或删除。',
```

In `errors.ts` `getOperationErrorMessage`, before the `if (message.trim())` fallthrough, add:

```ts
  if (code === 'CREDENTIAL_IN_USE') {
    const refs = Array.isArray(data?.references) ? data!.references : null
    const legacyIds = Array.isArray(data?.dependency_ids) ? data!.dependency_ids : null
    const legacyLists = ['agents', 'triggers', 'environments', 'sessions']
      .map((k) => (Array.isArray(data?.[k]) ? (data![k] as unknown[]).length : 0))
      .reduce((a, b) => a + b, 0)
    const otherCount = typeof data?.other_count === 'number' ? (data!.other_count as number) : 0
    const count = refs ? refs.length + otherCount : legacyIds ? legacyIds.length : legacyLists
    return t('managed.credentials.references.inUseSummary', { count })
  }
```

> `data` is typed `Record<string, unknown> | null` from `parseApiError`. Cast entries as needed; keep the existing null-safety style used elsewhere in the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run lib/managed/errors.test.ts`
Expected: PASS.

- [ ] **Step 5: Bump inventory count if `errors.test.ts` is newly created**

If you created `errors.test.ts`, it's a `.test.ts` (excluded from `sourceFileCount`) — no bump. If you added no new counted source file, skip. Then commit:

```bash
git add frontend/lib/managed/errors.ts frontend/lib/managed/errors.test.ts frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts
git commit -m "feat(credentials): CREDENTIAL_IN_USE error summary fallback (both shapes)"
```

---

## Task 10: Mount on model-connection detail + gate its confirm dialog

**Files:**
- Modify: `frontend/components/managed/credentials/model-connection-detail.tsx`
- Test: `frontend/components/managed/credentials/credential-detail-lifecycle.test.tsx` (extend existing lifecycle test)

**Interfaces:**
- Consumes: `useCredentialReferences` (Task 7), `<CredentialReferences>` (Task 8).
- Produces: an always-mounted informational references panel on the detail body; a `blocker`-variant panel inside the archive/delete confirm dialog; archive/delete submit disabled when `!canArchive` / `!canDelete`.

**Note:** Re-Read `model-connection-detail.tsx` before editing — the confirm flow is `confirmLifecycle` (`:141`) with `confirmAction` state. Mount the panel; gate the confirm button.

- [ ] **Step 1: Write the failing test**

```tsx
// extend frontend/components/managed/credentials/credential-detail-lifecycle.test.tsx
// Mock useCredentialReferences to return a blocking agent, assert the archive confirm
// button is disabled and the agent name/link is shown.
it('blocks archive when the credential is referenced', async () => {
  // arrange: mock '@/hooks/managed/use-credential-references' →
  //   useCredentialReferences: () => ({ data: { references: [{surface:'agent_model_binding',resourceType:'agent',id:'a1',name:'客服机器人'}], otherCount:0, canArchive:false, canDelete:false }, isLoading:false })
  // open the archive confirm dialog, then:
  expect(screen.getByText('客服机器人')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /archive|归档/i })).toBeDisabled()
})
```

> Follow the mocking + render setup already used in `credential-detail-lifecycle.test.tsx`. Add a `vi.mock('@/hooks/managed/use-credential-references', ...)` at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run components/managed/credentials/credential-detail-lifecycle.test.tsx`
Expected: FAIL — panel/name not rendered, button not disabled.

- [ ] **Step 3: Wire the hook, panel, and gate**

In `model-connection-detail.tsx`:
- Call the hook near other hooks: `const referencesQuery = useCredentialReferences(credential.id)`.
- Render `{referencesQuery.data && <CredentialReferences data={referencesQuery.data} variant="informational" />}` in the detail body.
- Inside the confirm dialog JSX, render `{referencesQuery.data && <CredentialReferences data={referencesQuery.data} variant="blocker" />}`.
- Compute `const blocked = confirmAction === 'archive' ? referencesQuery.data?.canArchive === false : confirmAction === 'delete' ? referencesQuery.data?.canDelete === false : false` and add `disabled={... || blocked}` to the confirm submit button; also guard at the top of `confirmLifecycle` with `if (blocked) return`.

> Match the exact confirm-button JSX and existing `disabled` expression in this file; add `|| blocked` to it. Import both symbols at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run components/managed/credentials/credential-detail-lifecycle.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/managed/credentials/model-connection-detail.tsx frontend/components/managed/credentials/credential-detail-lifecycle.test.tsx
git commit -m "feat(credentials): where-used panel + archive/delete gating on model detail"
```

---

## Task 11: Mount on service-credential detail + MCP vault (group) detail

**Files:**
- Modify: `frontend/components/managed/credentials/service-credential-detail.tsx`
- Modify: `frontend/components/managed/credentials/mcp-vault-detail.tsx`
- Test: extend the relevant existing detail tests (or add a focused render test per file)

**Interfaces:**
- Consumes: `useCredentialReferences` (service detail), `useCredentialGroupReferences` (vault/group detail), `<CredentialReferences>`.
- Produces: informational panel on both detail pages; blocker-variant panel + submit gating in the service-credential confirm dialog (mirror Task 10). For the MCP vault group, gate the group archive/delete confirm with `canArchive`/`canDelete` from `useCredentialGroupReferences`.

**Note:** Re-Read both files before editing. `service-credential-detail.tsx` has a `confirmAction` flow like the model detail (`:105`). `mcp-vault-detail.tsx` handles group archive + per-credential archive (`handleArchiveCred` `:335`) — wire the GROUP references (`useCredentialGroupReferences(id)`) to the group-level archive/delete confirm only. **This file is also edited by the service-credential create-flow initiative — keep changes confined to the references panel/gating section.**

- [ ] **Step 1: Write the failing tests**

Add, per file, a test mirroring Task 10 Step 1: mock the appropriate hook to return a blocking reference and assert (a) the consumer name renders, (b) the confirm submit is disabled. Use each file's existing test harness; if none exists for `mcp-vault-detail`, add `frontend/components/managed/credentials/mcp-vault-detail.references.test.tsx` with a minimal render (and bump `sourceFileCount`? No — `.test.tsx` is excluded, so no bump).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run components/managed/credentials/service-credential-detail && npx vitest run components/managed/credentials/mcp-vault-detail`
Expected: FAIL — panels/gating absent.

- [ ] **Step 3: Wire both files**

- `service-credential-detail.tsx`: identical pattern to Task 10 (informational panel in body, blocker panel in confirm dialog, gate submit via `canArchive`/`canDelete`), using `useCredentialReferences(credential.id)`.
- `mcp-vault-detail.tsx`: `const groupReferencesQuery = useCredentialGroupReferences(id)`; render informational panel in the vault body; in the group archive/delete confirm, render the blocker panel and gate the submit with `groupReferencesQuery.data?.canArchive/​canDelete`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run components/managed/credentials/service-credential-detail && npx vitest run components/managed/credentials/mcp-vault-detail`
Expected: PASS.

- [ ] **Step 5: Full frontend type-check + credentials test sweep, then commit**

Run: `cd frontend && npx tsc --noEmit && npx vitest run components/managed/credentials hooks/managed/use-credential-references.test.tsx lib/managed/errors.test.ts lib/i18n/credential-terminology.test.ts`
Expected: PASS (type-check clean; all credential tests green).

```bash
git add frontend/components/managed/credentials/service-credential-detail.tsx frontend/components/managed/credentials/mcp-vault-detail.tsx frontend/components/managed/credentials/service-credential-detail.test.tsx frontend/components/managed/credentials/mcp-vault-detail.references.test.tsx
git commit -m "feat(credentials): where-used panel on service + MCP vault detail"
```

---

## Final verification

- [ ] Backend: `cd backend && uv run pytest tests/ -q -k "credential or reference"` → all PASS.
- [ ] Backend error-catalog guard unaffected (no new code): `cd backend && uv run pytest tests/test_error_code_catalog_guard.py -q` → PASS.
- [ ] Frontend: `cd frontend && npx tsc --noEmit` → clean; `npx vitest run components/managed/credentials hooks/managed lib/managed lib/i18n/credential-terminology.test.ts` → PASS.
- [ ] Manual smoke (if a dev stack is available): archive a referenced model credential → confirm dialog shows the layered, clickable consumer list and the submit is disabled; archive an unused credential → succeeds.

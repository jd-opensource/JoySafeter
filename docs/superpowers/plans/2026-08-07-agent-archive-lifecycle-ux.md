# Agent Archive Lifecycle Closure & Action-Area Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent archiving reversible (new un-archive endpoint), state the true archive impact in the confirmation prompt, and flatten the agent detail action area into a toolbar with a working archived-agent path.

**Architecture:** Backend adds a `restore_agent` service method + `POST /agents/{id}/unarchive` endpoint that clears `archived_at` and recomputes the agent's paused cron triggers, mirroring the existing project-restore flow. Frontend replaces the Edit-button + three-dot menu on the agent detail page with a flat toolbar whose buttons vary by archived/active/read-only state, adds a `handleRestore` handler, and rewrites the archive confirmation copy plus new restore copy in both locales.

**Tech Stack:** Python (FastAPI, SQLAlchemy async), pytest; TypeScript/React (Next.js app router, TanStack Query), Vitest + Testing Library.

## Global Constraints

- Backend tests run from `backend/`: `cd backend && uv run pytest` (never bare `pytest` at repo root — pytest config lives only in `backend/pyproject.toml`).
- Frontend tests run from `frontend/`: `cd frontend && npx vitest run <path>`.
- i18n copy: the agent `archiveDescription` key exists in **two** places in each locale file (top-level `agents.*` and nested `managed.agents.*`); both must stay in sync. New keys: `restoreTitle`, `restoreDescription` (nested `managed.agents.*`), `common.restore`.
- Cron recompute uses the existing `_next_run_or_pause(trigger)` which already returns NULL when the target project/agent/environment is paused or archived — so recompute must run **after** `archived_at` is cleared in the same transaction.
- Terminated/archived sessions are NOT revived on restore.
- Do not touch `.deps/SkillSpector`.

---

### Task 1: Backend — trigger `resume_after_agent_restore`

Recompute cron trigger fire slots for a single agent, mirroring `resume_after_project_triggers_unpaused`. Because `_next_run_or_pause` already accounts for a paused/archived project/agent/environment, this method recomputes unconditionally and lets that helper decide NULL vs a future instant.

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_trigger_service.py` (add method after `resume_after_project_triggers_unpaused`, ~line 564)
- Test: `backend/tests/test_agent_restore.py` (create)

**Interfaces:**
- Consumes: `self._next_run_or_pause(trigger)`, `self._sync_config(trigger)`, `JoySafeterTrigger`, `AgentId` (all already imported in the service).
- Produces: `async def resume_after_agent_restore(self, agent_id: AgentId) -> None` — recomputes `next_run_at` for the agent's non-deleted cron triggers; no commit (caller owns the transaction).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_agent_restore.py`:

```python
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.utils.datetime import utc_now


async def _project_and_agent(db_session, *, name: str) -> tuple[Project, JoySafeterAgent]:
    org = Organization(id=f"org-{uuid.uuid4()}", name=f"{name} Org", slug=f"{name.lower()}-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name=name, slug=f"{name.lower()}-{uuid.uuid4()}")
    db_session.add_all([org, project])
    await db_session.commit()
    await db_session.refresh(project)
    agent = JoySafeterAgent(name=f"{name.lower()}-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return project, agent


async def _paused_cron_trigger(db_session, *, project: Project, agent: JoySafeterAgent) -> JoySafeterTrigger:
    trigger = JoySafeterTrigger(
        name=f"cron-{uuid.uuid4()}",
        type="cron",
        agent_id=agent.id,
        prompt_template="scheduled audit",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=None,  # simulate the post-archive paused state
        project_id=project.id,
        user_id="trigger-owner",
        org_id=project.org_id,
        concurrency_policy="allow",
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return trigger


@pytest.mark.asyncio
async def test_resume_after_agent_restore_rearms_enabled_cron_trigger(db_session):
    project, agent = await _project_and_agent(db_session, name="ResumeRearm")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)

    await JoySafeterTriggerService(db_session).resume_after_agent_restore(agent.id)
    await db_session.commit()

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger.id))).scalar_one()
    assert row.next_run_at is not None
    assert row.next_run_at > utc_now() - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_resume_after_agent_restore_keeps_disabled_trigger_paused(db_session):
    project, agent = await _project_and_agent(db_session, name="ResumeDisabled")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)
    trigger.enabled = False
    await db_session.commit()

    await JoySafeterTriggerService(db_session).resume_after_agent_restore(agent.id)
    await db_session.commit()

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger.id))).scalar_one()
    assert row.next_run_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_agent_restore.py -v`
Expected: FAIL with `AttributeError: 'JoySafeterTriggerService' object has no attribute 'resume_after_agent_restore'`.

- [ ] **Step 3: Add the method**

In `backend/app/joysafeter_domain/services/joysafeter_trigger_service.py`, insert directly after `resume_after_project_triggers_unpaused` (after line 564):

```python
    async def resume_after_agent_restore(self, agent_id: AgentId) -> None:
        """Recompute cron trigger fire slots after an agent is restored from archive.

        The caller owns the transaction and must clear the agent's ``archived_at``
        before calling this, so ``_next_run_or_pause`` sees the agent as live.
        Enabled cron triggers resume from the next future instant; disabled ones
        (and those whose project/environment is still paused/archived) stay paused
        with no due slot.
        """
        result = await self.db.execute(
            select(JoySafeterTrigger).where(
                JoySafeterTrigger.agent_id == agent_id,
                JoySafeterTrigger.type == "cron",
                JoySafeterTrigger.deleted_at.is_(None),
            )
        )
        for trigger in result.scalars().all():
            trigger.locked_by = None
            trigger.locked_at = None
            trigger.pending_slot_at = None
            trigger.slot_attempts = 0
            trigger.next_run_at = await self._next_run_or_pause(trigger)
            self._sync_config(trigger)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_agent_restore.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_trigger_service.py backend/tests/test_agent_restore.py
git commit -m "feat(triggers): recompute agent cron slots on restore"
```

---

### Task 2: Backend — `restore_agent` service + `POST /agents/{id}/unarchive` endpoint

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py` (add method after `archive_agent_with_sessions`, ~line 477)
- Modify: `backend/app/joysafeter_api/api/v1/agents.py` (add endpoint after `archive_agent`, ~line 737)
- Test: `backend/tests/test_agent_restore.py` (append)

**Interfaces:**
- Consumes: `self.get_agent`, `utc_now`, `JoySafeterTriggerService(self.db).resume_after_agent_restore`, `require_joysafeter_write`, `_agent_not_found_error`, `AgentService`.
- Produces:
  - Service: `async def restore_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool` — returns `False` when the agent is missing/out of scope; `True` when restored or already active (idempotent).
  - Endpoint: `POST /agents/{agent_id}/unarchive` → `{"status": "active"}`; function name `unarchive_agent` (importable in tests).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agent_restore.py`:

```python
from app.joysafeter_api.api.v1.agents import unarchive_agent
from app.joysafeter_domain.schemas.joysafeter_agent import JoySafeterUpdateAgentRequest
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import as_uuid


def _write_ctx(project_id: str, org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
    )


@pytest.mark.asyncio
async def test_unarchive_clears_archived_at_and_rearms_triggers(db_session):
    project, agent = await _project_and_agent(db_session, name="RestoreE2E")
    trigger = await _paused_cron_trigger(db_session, project=project, agent=agent)
    svc = JoySafeterAgentService(db_session)

    archived, _ = await svc.archive_agent_with_sessions(agent.id, project_id=project.id)
    assert archived is True
    db_session.expire_all()
    archived_row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent.id))).scalar_one()
    assert archived_row.archived_at is not None
    paused = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger.id))).scalar_one()
    assert paused.next_run_at is None

    result = await unarchive_agent(agent.id, db_session, _write_ctx(project.id, project.org_id))
    assert result == {"status": "active"}

    db_session.expire_all()
    restored = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent.id))).scalar_one()
    rearmed = (await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger.id))).scalar_one()
    assert restored.archived_at is None
    assert rearmed.next_run_at is not None


@pytest.mark.asyncio
async def test_unarchive_makes_agent_editable_again(db_session):
    project, agent = await _project_and_agent(db_session, name="RestoreEditable")
    svc = JoySafeterAgentService(db_session)
    await svc.archive_agent_with_sessions(agent.id, project_id=project.id)

    await unarchive_agent(agent.id, db_session, _write_ctx(project.id, project.org_id))

    # Update no longer rejected: service update succeeds after restore.
    updated = await svc.update_agent(
        agent.id,
        JoySafeterUpdateAgentRequest(description="edited after restore"),
        project_id=project.id,
    )
    assert updated is not None
    assert updated.description == "edited after restore"


@pytest.mark.asyncio
async def test_unarchive_is_idempotent_on_active_agent(db_session):
    project, agent = await _project_and_agent(db_session, name="RestoreIdempotent")

    result = await unarchive_agent(agent.id, db_session, _write_ctx(project.id, project.org_id))
    assert result == {"status": "active"}
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterAgent).where(JoySafeterAgent.id == agent.id))).scalar_one()
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_unarchive_missing_agent_raises_404(db_session):
    project, _agent = await _project_and_agent(db_session, name="RestoreMissing")
    missing_id = as_uuid(uuid.uuid4())

    with pytest.raises(AppError) as exc_info:
        await unarchive_agent(missing_id, db_session, _write_ctx(project.id, project.org_id))  # type: ignore[arg-type]

    assert exc_info.value.code == "AGENT_NOT_FOUND"
```

Before running, confirm the exact update-request schema class name and `update_agent` signature — verify with:
`cd backend && grep -n "class JoySafeterUpdateAgentRequest\|async def update_agent" app/joysafeter_domain/schemas/joysafeter_agent.py app/joysafeter_domain/services/joysafeter_agent_service.py`
If the names differ, adjust the import and the `update_agent` call in `test_unarchive_makes_agent_editable_again` accordingly. (This is the only test coupling to the update API; the rest use archive/unarchive only.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_agent_restore.py -v`
Expected: FAIL on import — `ImportError: cannot import name 'unarchive_agent'`.

- [ ] **Step 3: Add the service method**

In `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`, insert after `archive_agent_with_sessions` (after line 477):

```python
    async def restore_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        """Un-archive an agent and rearm its paused cron triggers in one transaction.

        Returns False when the agent does not exist (or is out of the given
        project scope). Returns True when restored, or when it was already active
        (idempotent, no side effects). Already-terminated sessions are left as-is.
        """
        agent = await self.get_agent(agent_id, project_id=project_id)
        if not agent:
            return False
        if agent.archived_at is None:
            return True

        from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService

        now = utc_now()
        agent.archived_at = None
        agent.updated_at = now
        await self.db.flush()  # make cleared archived_at visible to _next_run_or_pause
        await JoySafeterTriggerService(self.db).resume_after_agent_restore(agent_id)
        await self.db.commit()
        return True
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/joysafeter_api/api/v1/agents.py`, insert after `archive_agent` (after line 737):

```python
@router.post("/{agent_id}/unarchive", status_code=200)
async def unarchive_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = AgentService(db)
    restored = await svc.restore_agent(agent_id, project_id=auth_ctx.project_id)
    if not restored:
        raise _agent_not_found_error(agent_id)
    return {"status": "active"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_agent_restore.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Run the broader agent-lifecycle suite for regressions**

Run: `cd backend && uv run pytest tests/test_agent_lifecycle_active_tasks.py -q`
Expected: PASS (no behavior change to archive/delete).

- [ ] **Step 7: Commit**

```bash
git add backend/app/joysafeter_domain/services/joysafeter_agent_service.py backend/app/joysafeter_api/api/v1/agents.py backend/tests/test_agent_restore.py
git commit -m "feat(agents): add unarchive endpoint that restores agent and rearms triggers"
```

---

### Task 3: Frontend — i18n copy (archive rewrite + restore keys)

**Files:**
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/lib/i18n/locales/en.ts`

**Interfaces:**
- Produces translation keys consumed by Task 4: `common.restore`, `managed.agents.archiveDescription` (rewritten, both occurrences), top-level `agents.archiveDescription` (rewritten), `managed.agents.restoreTitle`, `managed.agents.restoreDescription`.

- [ ] **Step 1: Add `common.restore` (both files)**

`en.ts` — after line 10 (`archive: 'Archive',`) in the `common` block, add:
```typescript
      restore: 'Restore',
```
`zh.ts` — in the `common` block next to `archive: '归档',`, add:
```typescript
      restore: '恢复',
```

- [ ] **Step 2: Rewrite the archive description (both occurrences, both files)**

`en.ts` — replace BOTH occurrences (top-level `agents.archiveDescription` ~line 174 and nested `managed.agents.archiveDescription` ~line 525):
```typescript
        archiveDescription:
          'Archiving "{{name}}" will terminate all its running sessions, pause its cron triggers, and make its configuration read-only. You can restore it later. Continue?',
```
(top-level occurrence uses the same string with its existing indentation.)

`zh.ts` — replace BOTH occurrences (top-level ~line 276 and nested ~line 595):
```typescript
        archiveDescription:
          '归档 "{{name}}" 将终止其所有进行中的会话、暂停其定时触发器，并将配置设为只读。你可以稍后恢复。确定继续吗？',
```

- [ ] **Step 3: Add restore title/description (nested `managed.agents.*`, both files)**

`en.ts` — in the nested `managed.agents` block near `archiveDescription` (~line 526), add:
```typescript
        restoreTitle: 'Restore Agent',
        restoreDescription:
          'Restoring "{{name}}" will make it usable again and recompute the next run time of its cron triggers. Terminated sessions are not restored.',
```
`zh.ts` — in the nested `managed.agents` block near `archiveDescription` (~line 596), add:
```typescript
        restoreTitle: '恢复智能体',
        restoreDescription:
          '恢复 "{{name}}" 会将其重新设为可用，并重新计算其定时触发器的下次执行时间。已终止的会话不会恢复。',
```

- [ ] **Step 4: Verify locale files parse (typecheck)**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json`
Expected: no errors introduced by the locale edits. (If the repo uses a different typecheck command, use the project's `lint`/`typecheck` script.)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/i18n/locales/zh.ts frontend/lib/i18n/locales/en.ts
git commit -m "i18n(agents): state real archive impact and add restore copy"
```

---

### Task 4: Frontend — flat action-area toolbar + restore handler

Replace the Edit-button + three-dot `ActionMenu` in the detail page header with a flat toolbar. Active agents show `Start Session / Edit / Guided Edit / Archive / Delete`; archived agents show `Restore / Delete`; project-read-only disables all. Add `handleRestore`. Fix delete/restore guards so they work on archived agents (the current `currentAgentIsActive()` returns false when archived, which would make the exposed Delete/Restore buttons no-ops).

**Files:**
- Modify: `frontend/app/managed/agents/[agentId]/page.tsx`

**Interfaces:**
- Consumes: `apiResourcePath('agents', agentId, 'unarchive')`, `managedPost`, `ConfirmDialog`, translation keys from Task 3.
- Produces: `handleRestore` handler; toolbar rendering keyed off `isArchived` / `projectReadOnly`.

- [ ] **Step 1: Add a writable-agent guard (works regardless of archived state)**

In `page.tsx`, immediately after `currentAgentIsActive` (ends at line 136), add:

```tsx
  const currentAgentIsWritable = () => {
    if (!currentOperationScopeIsActive()) return false
    if (!currentProjectAllowsWrite()) return false
    const currentAgent = queryClient.getQueryData<Agent>(['agent', managedScope.key, agentId])
    return !!currentAgent && currentAgent.id === agent?.id
  }
```

- [ ] **Step 2: Point delete's guards at the writable guard**

In `handleDelete` (line 261) change the opening guard:
```tsx
  const handleDelete = async () => {
    if (!currentAgentIsWritable()) return
```
and inside its two `onConfirm`/mid-flow guards replace each `if (!currentAgentIsActive())` with `if (!currentAgentIsWritable())` (there is one at line 273 `|| !currentAgentIsActive()` → `|| !currentAgentIsWritable()`, and one at line 287). Leave `handleStartSession`, `handleGuidedEdit`, `handleArchive` using `currentAgentIsActive()` unchanged.

- [ ] **Step 3: Add `handleRestore`**

Insert after `handleArchive` (after line 259):

```tsx
  const handleRestore = () => {
    if (!currentAgentIsWritable()) return
    const currentAgent = queryClient.getQueryData<Agent>(['agent', managedScope.key, agentId])
    if (!currentAgent?.archived_at) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.agents.restoreTitle'),
      description: t('managed.agents.restoreDescription', { name: agent?.name }),
      confirmLabel: t('common.restore'),
      destructive: false,
      onConfirm: async () => {
        const action = nextAction()
        if (!action) return
        const { runId, scope } = action
        const requestScope = managedRequestScopeRef.current
        try {
          await managedPost(
            apiResourcePath('agents', agentId, 'unarchive'),
            {},
            managedRequestOptions(requestScope),
          )
          if (!isCurrentAction(runId, scope)) return
          queryClient.invalidateQueries({ queryKey: ['agent', requestScope.key, agentId] })
          setConfirmDialog((prev) => ({ ...prev, open: false }))
        } catch (e) {
          if (!isCurrentAction(runId, scope)) return
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          toastOperationError(t, e, 'common.operationFailed')
        }
      },
    })
  }
```

- [ ] **Step 4: Swap the icon import**

In the lucide import (line 7) add `ArchiveRestore`:
```tsx
import { Pencil, ChevronRight, Package, Globe, Play, Sparkles, Archive, ArchiveRestore, Trash2 } from 'lucide-react'
```

- [ ] **Step 5: Delete the `menuItems` block and replace the header action with the toolbar**

Remove the `const menuItems = ... ` block (lines 362–388). Replace the `action={...}` prop of `<PageHeader>` (lines 399–415) with:

```tsx
        action={
          <div className="flex items-center gap-2">
            {isArchived ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly}
                  onClick={handleRestore}
                >
                  <ArchiveRestore className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.restore')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly}
                  className="text-destructive hover:text-destructive"
                  onClick={handleDelete}
                >
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.delete')}
                </Button>
              </>
            ) : (
              <>
                <Button variant="default" size="sm" disabled={projectReadOnly} onClick={handleStartSession}>
                  <Play className="mr-1.5 h-3.5 w-3.5" />
                  {t('managed.agents.startSession')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly}
                  onClick={() => {
                    if (!currentAgentIsActive()) return
                    router.push(`/managed/agents/${agentId}/edit`)
                  }}
                >
                  <Pencil className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.edit')}
                </Button>
                <Button variant="outline" size="sm" disabled={projectReadOnly} onClick={handleGuidedEdit}>
                  <Sparkles className="mr-1.5 h-3.5 w-3.5" />
                  {t('managed.agents.guidedEdit')}
                </Button>
                <Button variant="outline" size="sm" disabled={projectReadOnly} onClick={handleArchive}>
                  <Archive className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.archive')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={projectReadOnly}
                  className="text-destructive hover:text-destructive"
                  onClick={handleDelete}
                >
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.delete')}
                </Button>
              </>
            )}
          </div>
        }
```

- [ ] **Step 6: Remove the now-unused `ActionMenu` import**

In the `@/components/managed/shared` import (lines 33–44), delete the `ActionMenu,` line. (`ActionMenu` was only used by the header menu; `AgentSessions` uses `DataTable`'s own `actionMenu` prop, not this component.)

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json`
Expected: no errors (no unused-import error for `ActionMenu`).

- [ ] **Step 8: Commit**

```bash
git add frontend/app/managed/agents/\[agentId\]/page.tsx
git commit -m "feat(agents): flat action toolbar with working archived-agent restore/delete"
```

---

### Task 5: Frontend — detail-page toolbar test

**Files:**
- Test: `frontend/app/managed/agents/[agentId]/page.test.tsx` (create)

**Interfaces:**
- Consumes: the exported default `AgentDetailPage`, translation keys (mock `t` returns the key verbatim, so assertions match key strings).

- [ ] **Step 1: Write the test**

Create `frontend/app/managed/agents/[agentId]/page.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const managedPost = vi.fn(() => Promise.resolve({}))
const AGENT_ID = 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122'
let agentPayload: Record<string, unknown>

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn((path: string) => {
    if (String(path).includes('/versions')) return Promise.resolve({ data: [] })
    if (String(path).includes('/sessions')) return Promise.resolve({ data: [] })
    return Promise.resolve(agentPayload)
  }),
  managedPost: (...args: unknown[]) => managedPost(...args),
  managedDelete: vi.fn(),
}))

vi.mock('@/lib/managed/agent-response-parsers', () => ({ parseAgentResponse: (x: unknown) => x }))
vi.mock('@/lib/managed/session-response-parsers', () => ({ parseSessionListResponse: (x: unknown) => x }))
vi.mock('@/lib/managed/errors', () => ({
  shouldRetryManagedResourceError: () => false,
  toastOperationError: vi.fn(),
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ key: 'scope', orgId: 'o', projectId: 'p' }),
  hasManagedRequestScope: () => true,
  managedRequestOptions: () => ({}),
  managedScopeKey: () => 'scope',
}))
vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: Object.assign(() => ({}), {
    getState: () => ({ currentOrgId: 'o', currentProjectId: 'p' }),
  }),
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => true,
  useCurrentProjectReadOnly: () => false,
}))
vi.mock('@/components/managed/agent/version-diff-view', () => ({ VersionDiffView: () => null }))
vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: ReactNode }) => <button type="button">{children}</button>,
  TabsContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/badge', () => ({ Badge: ({ children }: { children: ReactNode }) => <span>{children}</span> }))
vi.mock('@/components/managed/shared', () => ({
  PageHeader: ({ action }: { action?: ReactNode }) => <div>{action}</div>,
  StatusBadge: () => null,
  MonoId: () => null,
  RelativeTime: () => null,
  DataTable: () => null,
  FilterBar: () => null,
  ResourceErrorState: () => <div>error</div>,
  ConfirmDialog: ({
    open,
    confirmLabel,
    onConfirm,
  }: {
    open: boolean
    confirmLabel: string
    onConfirm: () => void
  }) =>
    open ? (
      <button type="button" onClick={onConfirm}>
        confirm:{confirmLabel}
      </button>
    ) : null,
}))

import AgentDetailPage from './page'

async function renderPage(): Promise<RenderResult> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const params = Promise.resolve({ agentId: AGENT_ID })
  await params
  let view!: RenderResult
  await act(async () => {
    view = render(
      <QueryClientProvider client={queryClient}>
        <AgentDetailPage params={params} />
      </QueryClientProvider>,
    )
  })
  return view
}

describe('AgentDetailPage action toolbar', () => {
  beforeEach(() => {
    managedPost.mockClear()
  })

  it('shows the full toolbar for an active agent', async () => {
    agentPayload = { id: AGENT_ID, name: 'My Agent', archived_at: null, updated_at: '2026-08-07T00:00:00Z' }
    await renderPage()
    await waitFor(() => expect(screen.getByText('managed.agents.startSession')).toBeTruthy())
    expect(screen.getByText('common.edit')).toBeTruthy()
    expect(screen.getByText('managed.agents.guidedEdit')).toBeTruthy()
    expect(screen.getByText('common.archive')).toBeTruthy()
    expect(screen.getByText('common.delete')).toBeTruthy()
    expect(screen.queryByText('common.restore')).toBeNull()
  })

  it('shows only restore and delete for an archived agent', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    }
    await renderPage()
    await waitFor(() => expect(screen.getByText('common.restore')).toBeTruthy())
    expect(screen.getByText('common.delete')).toBeTruthy()
    expect(screen.queryByText('managed.agents.startSession')).toBeNull()
    expect(screen.queryByText('common.archive')).toBeNull()
  })

  it('calls the unarchive endpoint when restore is confirmed', async () => {
    agentPayload = {
      id: AGENT_ID,
      name: 'My Agent',
      archived_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    }
    await renderPage()
    await waitFor(() => expect(screen.getByText('common.restore')).toBeTruthy())
    await act(async () => {
      fireEvent.click(screen.getByText('common.restore'))
    })
    await act(async () => {
      fireEvent.click(screen.getByText('confirm:common.restore'))
    })
    await waitFor(() => expect(managedPost).toHaveBeenCalled())
    expect(String(managedPost.mock.calls[0][0])).toContain(`/agents/${AGENT_ID}/unarchive`)
  })
})
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `cd frontend && npx vitest run app/managed/agents/\[agentId\]/page.test.tsx`
Expected: all three tests PASS. (If `screen`/`toBeTruthy` matchers need setup, mirror the assertions already used in `edit/page.test.tsx`, which uses `@testing-library/react` in this repo.)

- [ ] **Step 3: Commit**

```bash
git add frontend/app/managed/agents/\[agentId\]/page.test.tsx
git commit -m "test(agents): cover archive/restore action toolbar states"
```

---

## Self-Review

**Spec coverage:**
- Spec §1 (backend unarchive: trigger method, service, endpoint) → Tasks 1 & 2. ✓
- Spec §2 (no backend change for prompt info) → honored; nothing to build. ✓
- Spec §3 (flat toolbar, archived shows restore+delete, read-only disables, ConfirmDialog, scope debounce) → Task 4. ✓
- Spec §4 (archive copy rewrite both occurrences + restore copy + `common.restore`, zh & en) → Task 3. ✓
- Spec §5 (backend restore tests + frontend toolbar tests) → Tasks 1/2 (backend) & 5 (frontend). ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code and exact commands. The one verification-before-use note (update-request schema name in Task 2 Step 1) gives an explicit grep command rather than a vague "handle it".

**Type consistency:** `resume_after_agent_restore(agent_id)` defined in Task 1, called in Task 2's `restore_agent`. `restore_agent(agent_id, project_id=None) -> bool` defined in Task 2, called by endpoint `unarchive_agent`. Frontend `handleRestore` posts to `apiResourcePath('agents', agentId, 'unarchive')`, matching the endpoint path `/agents/{id}/unarchive`. `currentAgentIsWritable()` defined in Task 4 Step 1, used in Steps 2–3. i18n keys added in Task 3 match those referenced in Task 4 (`common.restore`, `managed.agents.restoreTitle`, `managed.agents.restoreDescription`) and Task 5 assertions.

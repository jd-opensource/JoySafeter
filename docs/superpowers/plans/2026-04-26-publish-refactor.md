# Agent 发布流程重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the two separate "发布" entry points into a single Wizard-led publish flow with Settings as read-only history, backed by a transactional `AgentPublishService` on the backend.

**Architecture:** New `AgentPublishService` orchestration layer handles freeze→create→activate in a single transaction. Frontend drops all adapters and directly uses 3 hooks (`usePublishAgent`, `useRollbackAgent`, `useRetireRelease`) backed by a thin `agentPublishService` HTTP client. Settings tab loses version management section and publish button; Build Wizard release stage becomes the sole publish entry.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Next.js + React Query + shadcn/ui (frontend)

**Spec:** `docs/superpowers/specs/2026-04-26-publish-refactor-design.md`

---

## File Structure

### Backend — New/Modified

| File | Responsibility |
|------|---------------|
| `backend/app/services/agent_publish_service.py` | **NEW** — orchestrates publish/rollback/retire with single-commit transactions |
| `backend/app/services/agent_release_service.py` | **MODIFY** — remove `self.commit()` from `publish_release`, `activate_release`, `retire_release` |
| `backend/app/services/agent_version_service.py` | **MODIFY** — remove `self.commit()` from `freeze_version`; delete `unfreeze_version` method |
| `backend/app/api/v1/agents.py` | **MODIFY** — add `/publish` and `/rollback` routes; delete `/freeze`, `/unfreeze`, `/releases` (POST create), `/activate` routes; rewire `/retire` |
| `backend/app/schemas/agent_release.py` | No change (already has `CreateAgentReleaseRequest`) |
| `backend/tests/test_services/test_agent_publish_service.py` | **NEW** — tests for publish, rollback, retire |

### Frontend — New

| File | Responsibility |
|------|---------------|
| `frontend/services/agentPublishService.ts` | **NEW** — HTTP client for `/publish`, `/rollback`, `/retire`, list |
| `frontend/hooks/queries/agentPublish.ts` | **NEW** — `usePublishAgent`, `useRollbackAgent`, `useRetireRelease`, `useReleaseHistory` |

### Frontend — Delete

| File | Reason |
|------|--------|
| `frontend/components/agents/agent-build/agent-release-adapter.ts` | Replaced by backend orchestration |
| `frontend/components/agents/release-manager.tsx` | No longer needed — no manual version/runtime selection |
| `frontend/components/editors/graph-builder/services/deploymentAdapter.ts` | Thin shim over deleted adapter |

### Frontend — Rewrite

| File | Change |
|------|--------|
| `frontend/components/agents/agent-build/agent-release-stage.tsx` | Three-state UI, uses `usePublishAgent` |
| `frontend/components/agents/agent-settings-tab.tsx` | Remove sections 3-4, add release history |
| `frontend/components/editors/graph-builder/hooks/useDeploymentHistory.ts` | Use new hooks instead of adapter |
| `frontend/components/editors/graph-builder/components/DeploymentHistoryPanel.tsx` | Adapt to new hook API |
| `frontend/components/editors/graph-builder/components/DeploymentVersionsList.tsx` | Update type imports |
| `frontend/components/editors/graph-builder/CodeEditorPage.tsx` | Use `usePublishAgent` |
| `frontend/components/editors/graph-builder/stores/saveStore.ts` | Remove `deployedAt` |
| `frontend/components/editors/graph-builder/AgentBuilder.tsx` | Remove auto-unfreeze logic |
| `frontend/components/agents/agent-build/__tests__/agent-build-stages.test.tsx` | Update mocks |
| `frontend/hooks/queries/agentReleases.ts` | Remove deleted hooks |
| `frontend/hooks/queries/agentVersions.ts` | Remove freeze/unfreeze hooks |
| `frontend/services/agentReleaseService.ts` | Remove `.publish()`, `.activate()` |
| `frontend/services/agentVersionService.ts` | Remove `.freeze()`, `.unfreeze()` |
| `frontend/lib/i18n/locales/en.ts` | Update i18n keys |
| `frontend/lib/i18n/locales/zh.ts` | Update i18n keys |

---

## Task 1: Backend — Remove `self.commit()` from sub-service methods

These methods are called by the new `AgentPublishService` which owns the transaction boundary. Removing their internal commits makes them composable within a single transaction.

**Files:**
- Modify: `backend/app/services/agent_version_service.py:92-103` (freeze_version) and `:104-125` (delete unfreeze_version)
- Modify: `backend/app/services/agent_release_service.py:75` (publish_release), `:79-103` (activate_release), `:84-125` (retire_release)

- [ ] **Step 1: Remove `self.commit()` from `AgentVersionService.freeze_version()`**

In `backend/app/services/agent_version_service.py`, find `freeze_version` method (around line 92). Delete the `await self.commit()` line at the end (keeping everything else — validate, update, flush are via repo). Also delete the entire `unfreeze_version()` method (lines ~104-125).

- [ ] **Step 2: Remove `self.commit()` from `AgentReleaseService` methods**

In `backend/app/services/agent_release_service.py`:
- `publish_release()` (line 75): delete `await self.commit()`
- `activate_release()`: find and delete `await self.commit()`
- `retire_release()`: find and delete `await self.commit()`

Keep the logger calls and return statements.

- [ ] **Step 3: Verify the codebase still starts**

Run: `cd backend && python -c "from app.services.agent_version_service import AgentVersionService; from app.services.agent_release_service import AgentReleaseService; print('OK')"`

Expected: `OK` (no import errors)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent_version_service.py backend/app/services/agent_release_service.py
git commit -m "refactor: remove self.commit() from orchestrated sub-service methods

freeze_version, publish_release, activate_release, retire_release no
longer own their transaction boundary. Delete unfreeze_version entirely."
```

---

## Task 2: Backend — Create `AgentPublishService`

The orchestration layer that composes sub-service calls in a single transaction.

**Files:**
- Create: `backend/app/services/agent_publish_service.py`
- Create: `backend/tests/test_services/test_agent_publish_service.py`

- [ ] **Step 1: Create `agent_publish_service.py`**

Create file `backend/app/services/agent_publish_service.py`:

```python
"""
AgentPublishService — high-level publish/rollback/retire orchestration.

All sub-service calls share the same AsyncSession. Only this service
calls commit — sub-services only flush.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.models.agent import AgentRelease, AgentVersion
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.schemas.agent_release import CreateAgentReleaseRequest
from app.services.agent_release_service import AgentReleaseService
from app.services.agent_version_service import AgentVersionService

from .base import BaseService


class AgentPublishService(BaseService):

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.version_svc = AgentVersionService(db)
        self.release_svc = AgentReleaseService(db)
        self.agent_repo = AgentRepository(db)
        self.version_repo = AgentVersionRepository(db)

    async def publish(self, agent_id: uuid.UUID, user_id: str) -> dict:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        version = await self._resolve_current_draft(agent)

        if version.status == "draft":
            await self.version_svc.freeze_version(version.id)

        runtime_kind = self._infer_runtime_kind(version.definition_kind)
        release_data = CreateAgentReleaseRequest(
            agent_version_id=version.id,
            runtime_kind=runtime_kind,
        )
        release = await self.release_svc.publish_release(
            agent_id, user_id, release_data
        )

        await self.release_svc.activate_release(agent_id, release.id)

        await self.safe_commit()
        return {"agent": agent, "release": release}

    async def rollback(self, agent_id: uuid.UUID, release_id: uuid.UUID) -> dict:
        await self.release_svc.activate_release(agent_id, release_id)
        await self.safe_commit()
        agent = await self.agent_repo.get(agent_id)
        return {"agent": agent}

    async def retire(self, agent_id: uuid.UUID, release_id: uuid.UUID) -> dict:
        release = await self.release_svc.retire_release(agent_id, release_id)
        await self.safe_commit()
        return {"release": release}

    async def _resolve_current_draft(self, agent) -> AgentVersion:
        if not agent.current_draft_version_id:
            raise BadRequestException("Agent has no draft version")
        version = await self.version_repo.get(agent.current_draft_version_id)
        if not version:
            raise NotFoundException("Draft version not found")
        return version

    @staticmethod
    def _infer_runtime_kind(definition_kind: str) -> str:
        if definition_kind in ("graph", "hybrid"):
            return "graph"
        if definition_kind == "code":
            return "sandbox"
        return "graph"
```

- [ ] **Step 2: Create test file**

Create `backend/tests/test_services/test_agent_publish_service.py`:

```python
"""Tests for AgentPublishService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agent_publish_service import AgentPublishService


class TestInferRuntimeKind:
    def test_graph(self):
        assert AgentPublishService._infer_runtime_kind("graph") == "graph"

    def test_hybrid(self):
        assert AgentPublishService._infer_runtime_kind("hybrid") == "graph"

    def test_code(self):
        assert AgentPublishService._infer_runtime_kind("code") == "sandbox"

    def test_unknown_defaults_to_graph(self):
        assert AgentPublishService._infer_runtime_kind("whatever") == "graph"
```

- [ ] **Step 3: Run the test**

Run: `cd backend && python -m pytest tests/test_services/test_agent_publish_service.py -v`

Expected: 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent_publish_service.py backend/tests/test_services/test_agent_publish_service.py
git commit -m "feat: add AgentPublishService — transactional publish/rollback/retire"
```

---

## Task 3: Backend — Add API routes and remove old ones

Wire up the new service to HTTP endpoints, delete the 4 old endpoints.

**Files:**
- Modify: `backend/app/api/v1/agents.py`

- [ ] **Step 1: Add import for `AgentPublishService`**

At the top of `backend/app/api/v1/agents.py`, add:

```python
from app.services.agent_publish_service import AgentPublishService
```

And add a Pydantic model for the rollback request body (can be inline or in schemas):

```python
from pydantic import BaseModel as PydanticBaseModel

class RollbackRequest(PydanticBaseModel):
    release_id: uuid.UUID
```

- [ ] **Step 2: Add `POST /{agent_id}/publish` route**

Add after the existing release routes (around line 309):

```python
@router.post("/{agent_id}/publish")
async def publish_agent(
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_workspace_role("admin")),
):
    service = AgentPublishService(db)
    result = await service.publish(agent_id, current_user.id)
    return BaseResponse(data=result)
```

- [ ] **Step 3: Add `POST /{agent_id}/rollback` route**

```python
@router.post("/{agent_id}/rollback")
async def rollback_agent(
    agent_id: uuid.UUID,
    body: RollbackRequest,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_workspace_role("admin")),
):
    service = AgentPublishService(db)
    result = await service.rollback(agent_id, body.release_id)
    return BaseResponse(data=result)
```

- [ ] **Step 4: Rewire `POST /{agent_id}/releases/{release_id}/retire`**

Find the existing retire route (line ~309). Change it from instantiating `AgentReleaseService` to using `AgentPublishService`:

```python
@router.post("/{agent_id}/releases/{release_id}/retire")
async def retire_release(
    agent_id: uuid.UUID,
    release_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_workspace_role("admin")),
):
    service = AgentPublishService(db)
    result = await service.retire(agent_id, release_id)
    return BaseResponse(data=result)
```

- [ ] **Step 5: Delete the 4 old routes**

Delete these route handlers from `agents.py`:
- `POST /{agent_id}/versions/{version_id}/freeze` (line ~212)
- `POST /{agent_id}/versions/{version_id}/unfreeze` (line ~225)
- `POST /{agent_id}/releases` create (line ~266)
- `POST /{agent_id}/releases/{release_id}/activate` (line ~296)

Keep these:
- `GET /{agent_id}/releases` (list)
- `GET /{agent_id}/releases/{release_id}` (get)

- [ ] **Step 6: Verify imports are clean**

Run: `cd backend && python -c "from app.api.v1.agents import router; print('OK')"`

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/agents.py
git commit -m "feat: add /publish and /rollback endpoints, remove 4 old granular endpoints"
```

---

## Task 4: Frontend — Create `agentPublishService` and `agentPublish` hooks

The new frontend data layer — thin HTTP client and React Query hooks.

**Files:**
- Create: `frontend/services/agentPublishService.ts`
- Create: `frontend/hooks/queries/agentPublish.ts`

- [ ] **Step 1: Create `agentPublishService.ts`**

Create `frontend/services/agentPublishService.ts`:

```typescript
'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { AgentRelease } from '@/types/agent-release'

export const agentPublishService = {
  async publish(agentId: string, workspaceId: string) {
    const res = await apiPost<{ agent: any; release: AgentRelease }>(
      `agents/${agentId}/publish?workspace_id=${workspaceId}`,
    )
    return res
  },

  async rollback(agentId: string, releaseId: string, workspaceId: string) {
    const res = await apiPost<{ agent: any }>(
      `agents/${agentId}/rollback?workspace_id=${workspaceId}`,
      { release_id: releaseId },
    )
    return res
  },

  async retire(agentId: string, releaseId: string, workspaceId: string) {
    const res = await apiPost<AgentRelease>(
      `agents/${agentId}/releases/${releaseId}/retire?workspace_id=${workspaceId}`,
    )
    return res
  },

  async list(agentId: string, workspaceId: string): Promise<AgentRelease[]> {
    const res = await apiGet<AgentRelease[]>(
      `agents/${agentId}/releases?workspace_id=${workspaceId}`,
    )
    return res
  },
}
```

- [ ] **Step 2: Create `agentPublish.ts` hooks**

Create `frontend/hooks/queries/agentPublish.ts`:

```typescript
'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentPublishService } from '@/services/agentPublishService'
import { agentKeys } from './agents'
import { STALE_TIME } from './constants'

export const publishKeys = {
  all: (agentId: string) => [...agentKeys.all, 'releases', agentId] as const,
  list: (agentId: string, workspaceId: string) =>
    [...publishKeys.all(agentId), 'list', workspaceId] as const,
}

export function useReleaseHistory(agentId: string, workspaceId: string) {
  return useQuery({
    queryKey: publishKeys.list(agentId, workspaceId),
    queryFn: () => agentPublishService.list(agentId, workspaceId),
    enabled: !!agentId && !!workspaceId,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function usePublishAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, workspaceId }: { agentId: string; workspaceId: string }) =>
      agentPublishService.publish(agentId, workspaceId),
    onSuccess: (_, { agentId, workspaceId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, workspaceId) })
    },
  })
}

export function useRollbackAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      releaseId,
      workspaceId,
    }: {
      agentId: string
      releaseId: string
      workspaceId: string
    }) => agentPublishService.rollback(agentId, releaseId, workspaceId),
    onSuccess: (_, { agentId, workspaceId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, workspaceId) })
    },
  })
}

export function useRetireRelease() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      releaseId,
      workspaceId,
    }: {
      agentId: string
      releaseId: string
      workspaceId: string
    }) => agentPublishService.retire(agentId, releaseId, workspaceId),
    onSuccess: (_, { agentId, workspaceId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.all(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId, workspaceId) })
    },
  })
}
```

Verify `agentKeys` import path and `STALE_TIME` import are correct by checking existing hooks in `agentReleases.ts`.

- [ ] **Step 3: Verify no TypeScript errors**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

Expected: No errors in the new files (existing files may have errors from stale imports — those are fixed in later tasks).

- [ ] **Step 4: Commit**

```bash
git add frontend/services/agentPublishService.ts frontend/hooks/queries/agentPublish.ts
git commit -m "feat: add agentPublishService and agentPublish hooks"
```

---

## Task 5: Frontend — Rewrite `AgentReleaseStage`

The sole publish entry point. Three-state UI: unpublished, published, publishing.

**Files:**
- Modify: `frontend/components/agents/agent-build/agent-release-stage.tsx` (full rewrite)

- [ ] **Step 1: Rewrite `agent-release-stage.tsx`**

Replace the entire component. The new version:
- Imports `usePublishAgent`, `useRollbackAgent`, `useRetireRelease`, `useReleaseHistory` from `agentPublish`
- No longer imports `agentReleaseAdapter`, `useActivateRelease`, `useRetireRelease` from old modules
- Three UI states: **unpublished** (hero publish button), **published** (green status card + history), **publishing** (loading)
- History list shows "版本 N · 发布于 DATE" instead of "#N ready graph Active"
- "回滚到此版本" replaces "Activate"
- "退役" in `···` overflow menu replaces standalone button
- Uses new i18n keys: `agents.build.release.publish`, `.publishNew`, `.currentActive`, `.history`, `.rollback`

Key changes from current code:
- Delete `deriveRuntimeKind` function (moved to backend)
- Delete `agentReleaseAdapter.publish(...)` call → `publishAgent.mutate({ agentId: agent.id, workspaceId })`
- Delete the manual query key invalidation (handled by hook `onSuccess`)
- Delete the Published/Not Published badge → replace with green status card

- [ ] **Step 2: Run existing test**

Run: `cd frontend && npx jest components/agents/agent-build/__tests__/agent-build-stages.test.tsx --no-coverage 2>&1 | tail -20`

Expected: Tests may fail due to changed component structure — will fix in Task 12.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/agents/agent-build/agent-release-stage.tsx
git commit -m "feat: rewrite AgentReleaseStage — three-state UI, single publish entry"
```

---

## Task 6: Frontend — Rewrite `AgentSettingsTab`

Remove version management section, convert release management to read-only history.

**Files:**
- Modify: `frontend/components/agents/agent-settings-tab.tsx`

- [ ] **Step 1: Rewrite settings tab**

Changes:
- Remove imports: `useFreezeVersion`, `useUnfreezeVersion` from `agentVersions`, `useActivateRelease` from `agentReleases`, `ReleaseManager`
- Add imports: `useReleaseHistory`, `useRollbackAgent`, `useRetireRelease` from `agentPublish`
- Delete Section 3 (版本管理) entirely — the collapsible card with freeze/unfreeze buttons (lines ~199-307)
- Rename Section 4: `t('agents.detail.releaseManagement')` → `t('agents.detail.releaseHistory')`
- Remove the "Publish Release" button that opens `ReleaseManager` dialog
- Remove `ReleaseManager` dialog mount at bottom
- Remove state: `versionDialogOpen`, `releaseDialogOpen`, `versionsOpen`
- Keep `releasesOpen` state for collapsible
- Replace per-release "Activate"/"Retire" buttons with:
  - "回滚到此版本" → `rollbackAgent.mutate(...)` (for non-active, ready releases)
  - "退役" in `···` menu → `retireRelease.mutate(...)`
- Add a "前往发布阶段" link button that navigates to `?stage=release`
- Display release info as "版本 N · 发布于 DATE" (no `status`, `runtime_kind` badges)

- [ ] **Step 2: Verify renders without crash**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep agent-settings-tab`

Expected: No errors for this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/agents/agent-settings-tab.tsx
git commit -m "refactor: settings tab — remove version management, convert to release history"
```

---

## Task 7: Frontend — Rewrite Graph Builder deployment layer

Replace adapter layer with direct hook usage.

**Files:**
- Delete: `frontend/components/editors/graph-builder/services/deploymentAdapter.ts`
- Modify: `frontend/components/editors/graph-builder/hooks/useDeploymentHistory.ts`
- Modify: `frontend/components/editors/graph-builder/components/DeploymentHistoryPanel.tsx`
- Modify: `frontend/components/editors/graph-builder/components/DeploymentVersionsList.tsx`
- Modify: `frontend/components/editors/graph-builder/CodeEditorPage.tsx`
- Modify: `frontend/components/editors/graph-builder/stores/saveStore.ts`
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx`

- [ ] **Step 1: Delete `deploymentAdapter.ts`**

```bash
rm frontend/components/editors/graph-builder/services/deploymentAdapter.ts
```

- [ ] **Step 2: Rewrite `useDeploymentHistory.ts`**

Replace all `deploymentAdapter` calls:
- `deploymentAdapter.list(...)` → use `agentPublishService.list(...)` directly (or `useReleaseHistory` if the hook can be composed)
- `deploymentAdapter.activate(...)` → `agentPublishService.rollback(...)`
- `deploymentAdapter.retire(...)` → `agentPublishService.retire(...)`

Keep the Graph Builder-specific logic: `fetchVersionState` (canvas preview via `agentVersionService.get`), version mapping, preview state management.

Update exported types (`GraphDeploymentVersion`, `GraphDeploymentStatus`, `GraphVersionState`) to match new data shapes — release data now comes from `AgentRelease` type directly instead of adapter's `AgentReleaseVersion` mapping.

- [ ] **Step 3: Update `DeploymentHistoryPanel.tsx`**

Adapt to any changes in `useDeploymentHistory` return types. The component is driven entirely by the hook, so changes should be limited to type updates.

- [ ] **Step 4: Update `DeploymentVersionsList.tsx`**

Update type imports from `useDeploymentHistory` if the exported type names or shapes changed.

- [ ] **Step 5: Rewrite `CodeEditorPage.tsx`**

- Remove import of `deploymentAdapter`
- Add `usePublishAgent` hook
- Replace `deploymentAdapter.deploy(graphId, versionId, workspaceId, 'code')` with `publishAgent.mutate({ agentId: graphId, workspaceId })`
- Remove `saveStore.deployedAt` reads and `setDeployedAt` calls

- [ ] **Step 6: Clean up `saveStore.ts`**

Remove `deployedAt: string | null` from `SaveState` interface (line 22) and `setDeployedAt` action (line 91). Remove initial value and reset logic for these fields.

- [ ] **Step 7: Clean up `AgentBuilder.tsx`**

- Remove `useUnfreezeVersion` import (line 8)
- Remove `const unfreezeVersion = useUnfreezeVersion()` (line 84)
- Delete the entire `useEffect` block (lines 87-109) that auto-unfreezes frozen versions

- [ ] **Step 8: Verify TypeScript**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -40`

Expected: No errors in graph-builder files.

- [ ] **Step 9: Commit**

```bash
git add -A frontend/components/editors/graph-builder/
git commit -m "refactor: graph builder — remove deployment adapter, use publish hooks directly"
```

---

## Task 8: Frontend — Delete old files and clean up stale exports

Remove adapter, dialog, and stale hooks/service methods.

**Files:**
- Delete: `frontend/components/agents/agent-build/agent-release-adapter.ts`
- Delete: `frontend/components/agents/release-manager.tsx`
- Modify: `frontend/hooks/queries/agentReleases.ts`
- Modify: `frontend/hooks/queries/agentVersions.ts`
- Modify: `frontend/services/agentReleaseService.ts`
- Modify: `frontend/services/agentVersionService.ts`

- [ ] **Step 1: Delete adapter and dialog**

```bash
rm frontend/components/agents/agent-build/agent-release-adapter.ts
rm frontend/components/agents/release-manager.tsx
```

- [ ] **Step 2: Clean `agentReleases.ts`**

Remove `usePublishRelease` and `useActivateRelease` from `frontend/hooks/queries/agentReleases.ts`. Keep `releaseKeys`, `useReleases` (if still imported elsewhere), and the file structure.

If `useRetireRelease` is still exported here AND in the new `agentPublish.ts`, remove it from here to avoid duplication.

Check: `grep -r "from.*agentReleases" frontend/ --include="*.ts" --include="*.tsx"` to see remaining consumers.

- [ ] **Step 3: Clean `agentVersions.ts`**

Remove `useFreezeVersion` (line ~118) and `useUnfreezeVersion` (line ~144) from `frontend/hooks/queries/agentVersions.ts`. Keep `useVersions`, `useVersion`, `useCreateVersion`, `useUpdateVersion`, `useVersionGraphState`.

- [ ] **Step 4: Clean `agentReleaseService.ts`**

Remove `.publish()` and `.activate()` methods from `frontend/services/agentReleaseService.ts`. Keep `.list()`, `.get()`, `.retire()` (if still used for direct queries).

- [ ] **Step 5: Clean `agentVersionService.ts`**

Remove `.freeze()` (line ~51) and `.unfreeze()` (line ~62) from `frontend/services/agentVersionService.ts`. Keep `.list()`, `.get()`, `.create()`, `.update()`.

- [ ] **Step 6: Verify no broken imports**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -40`

Expected: No import errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/agents/agent-build/agent-release-adapter.ts \
  frontend/components/agents/release-manager.tsx \
  frontend/hooks/queries/agentReleases.ts \
  frontend/hooks/queries/agentVersions.ts \
  frontend/services/agentReleaseService.ts \
  frontend/services/agentVersionService.ts
git commit -m "refactor: delete adapter/dialog, remove stale hooks and service methods"
```

---

## Task 9: Frontend — Update i18n keys

Replace developer-facing terminology with user-facing language.

**Files:**
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Update `en.ts`**

In `agents.build.release.*` section:
- Replace `kicker: 'Release lifecycle'` → delete key
- Replace `title: 'Publish and manage releases'` → `title: 'Publish your Agent'`
- Replace `subtitle: 'Release freezes the current...'` → `subtitle: 'Once published, your Agent is available via chat, tasks, and API.'`
- Replace `publishDraft: 'Publish Draft'` → `publish: 'Publish'`
- Keep `releases` key → rename to `history: 'Version history'`
- Keep `empty` key → `empty: 'No releases yet.'`
- Add: `publishNew: 'Publish new version'`
- Add: `currentActive: 'Currently published'`
- Add: `rollback: 'Roll back to this version'`

In `agents.detail.*` section:
- Replace `releaseManagement: 'Release Management'` → `releaseHistory: 'Release History'`
- Add: `goToPublish: 'Go to publish'`
- Delete: `publishReleaseTitle`, `publishReleaseDescription`, `noFrozenVersions`, `selectFrozenVersion`, `runtimeKind`, `runtimeKindOptions.*`, `runtimeBinding`, `publishRelease`, `publishingRelease`
- Delete: `versionManagement`, `freezeVersion`, `freezingVersion`, `unfreezeVersion`, `unfreezingVersion`

In `workspace.*` section:
- Delete or keep based on whether other features use them. Check with grep first:
  `grep -r "workspace\.deploy[^e]" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v i18n`

- [ ] **Step 2: Update `zh.ts`**

Same structural changes as `en.ts`, with Chinese translations:
- `title: '发布你的 Agent'`
- `subtitle: '发布后即可通过对话、任务和 API 使用'`
- `publish: '发布'`
- `publishNew: '发布新版本'`
- `currentActive: '当前已发布'`
- `history: '历史版本'`
- `rollback: '回滚到此版本'`
- `releaseHistory: '发布历史'`
- `goToPublish: '前往发布阶段'`

- [ ] **Step 3: Verify no missing keys at runtime**

Run: `cd frontend && grep -r "agents\.build\.release\." --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v i18n`

Cross-reference every key used in components with the i18n files.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts
git commit -m "refactor: update i18n — user-facing publish terminology"
```

---

## Task 10: Frontend — Update tests

Fix the test file that mocks deleted modules.

**Files:**
- Modify: `frontend/components/agents/agent-build/__tests__/agent-build-stages.test.tsx`

- [ ] **Step 1: Update test mocks and assertions**

The test file mocks `agentReleases` and `agent-release-adapter`. Update:
- Replace `agentReleases` mock with `agentPublish` mock
- Remove `agent-release-adapter` mock
- Update test assertions to match the new component structure (new button text, new i18n keys)
- `baseStageProps` should still work as-is (agent + version + workspaceId)

- [ ] **Step 2: Run the tests**

Run: `cd frontend && npx jest components/agents/agent-build/__tests__/agent-build-stages.test.tsx --no-coverage -v`

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/agents/agent-build/__tests__/agent-build-stages.test.tsx
git commit -m "test: update agent-build-stages tests for new publish hooks"
```

---

## Task 11: Full verification

End-to-end check that everything compiles, tests pass, and no stale references remain.

**Files:** None (verification only)

- [ ] **Step 1: Backend import check**

Run: `cd backend && python -c "from app.api.v1.agents import router; from app.services.agent_publish_service import AgentPublishService; print('All imports OK')"`

- [ ] **Step 2: Backend tests**

Run: `cd backend && python -m pytest tests/test_services/test_agent_publish_service.py -v`

Expected: All PASS.

- [ ] **Step 3: Frontend TypeScript check**

Run: `cd frontend && npx tsc --noEmit --pretty`

Expected: No errors.

- [ ] **Step 4: Frontend tests**

Run: `cd frontend && npx jest --no-coverage 2>&1 | tail -20`

Expected: All tests PASS.

- [ ] **Step 5: Grep for stale references**

```bash
grep -r "agentReleaseAdapter\|release-manager\|deploymentAdapter\|usePublishRelease\|useFreezeVersion\|useUnfreezeVersion\|useActivateRelease" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test."
```

Expected: No results (all references cleaned up).

```bash
grep -r "unfreeze_version\|/freeze\|/unfreeze\|/activate" backend/app/api/ --include="*.py"
```

Expected: No route handlers for deleted endpoints.

- [ ] **Step 6: Final commit (if any cleanup needed)**

```bash
git add -A && git commit -m "chore: final cleanup after publish refactor"
```

# Agent Build Shell Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Visual Agent Studio into a generic Agent lifecycle shell with Visual as one builder surface.

**Architecture:** Add a reusable `AgentBuildShell` that owns stage navigation and top-level lifecycle rendering. Keep `AgentStudioShell` as the Visual wrapper and move canvas-specific responsibilities into a `VisualBuilderSurface`. In Studio mode, `BuilderToolbar` becomes a canvas toolbar that navigates to Test Lab and Release instead of running or publishing directly.

**Tech Stack:** Next.js client components, React, Zustand stores, React Query hooks, Vitest + Testing Library.

---

### Task 1: Add Generic Shell Contract

**Files:**
- Create: `frontend/components/agents/agent-build/agent-build-types.ts`
- Create: `frontend/components/agents/agent-build/agent-build-shell.tsx`
- Test: `frontend/components/agents/agent-build/__tests__/agent-build-shell.test.tsx`

- [ ] Write tests that prove the shell renders configured stages and syncs stage changes to the URL.
- [ ] Implement `AgentBuildShell` with generic stage configs, top bar, nav, and render callback.
- [ ] Run the shell test and commit.

### Task 2: Make Visual Studio a Surface Wrapper

**Files:**
- Create: `frontend/components/agents/studio/visual-builder-surface.tsx`
- Modify: `frontend/components/agents/studio/agent-studio-shell.tsx`
- Modify: `frontend/components/agents/studio/studio-types.ts`
- Test: `frontend/components/agents/studio/__tests__/agent-studio-shell.test.tsx`

- [ ] Write tests proving Visual Studio still supports existing `canvas` and `test-lab` stages.
- [ ] Rework `AgentStudioShell` to delegate lifecycle rendering to `AgentBuildShell`.
- [ ] Render `VisualBuilderSurface` in the visual build stage.
- [ ] Run Studio shell tests and commit.

### Task 3: Remove Old Runtime/Release Ownership from Canvas Toolbar

**Files:**
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx`
- Modify: `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`
- Test: `frontend/components/editors/graph-builder/components/__tests__/builder-toolbar-add-node.test.tsx`

- [ ] Write tests proving Studio toolbar shows Test Lab and Release navigation, not `Run Draft`, direct publish, deployment history, or API access.
- [ ] Pass `onOpenTestLab` and `onOpenRelease` through `AgentBuilder`.
- [ ] In Studio mode, make toolbar actions navigate instead of calling `startExecution` or `deploymentAdapter.deploy`.
- [ ] Run toolbar tests and commit.

### Task 4: Add Release and Usage Stages

**Files:**
- Create: `frontend/components/agents/studio/studio-release-stage.tsx`
- Create: `frontend/components/agents/studio/studio-usage-stage.tsx`
- Modify: `frontend/components/agents/studio/agent-studio-shell.tsx`
- Test: `frontend/components/agents/studio/__tests__/agent-studio-shell.test.tsx`

- [ ] Write tests proving Release and Usage render real lifecycle surfaces instead of placeholders.
- [ ] Implement Release with publish, release list, activate, and retire actions using existing hooks/adapters.
- [ ] Implement Usage with API access and business usage entry points.
- [ ] Run Studio tests and commit.

### Task 5: Verify Integration

**Files:**
- No new production files.

- [ ] Run targeted frontend tests for Agent Build, Studio, toolbar, execution adapter, and Test Lab.
- [ ] Run frontend type-check.
- [ ] Review diff for architecture boundary violations.

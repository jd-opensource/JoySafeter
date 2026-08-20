# Quickstart Capability Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Quickstart capability story across Agent generation, real Skill/MCP configuration, truthful protection states, and runtime evidence.

**Architecture:** Add pure capability contracts first, extend the existing backend generation contract with a bounded Skill catalog, then integrate focused Capability Plan and Evidence components into the current Quickstart page. Preserve existing resource APIs and explicit confirmation gates.

**Tech Stack:** Next.js 16, React, TypeScript, TanStack Query, Vitest, Testing Library, FastAPI, Pydantic, Pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-20-quickstart-capability-closure-design.md`

## Global Constraints

- Desktop web only.
- No new frontend dependency.
- Do not touch unrelated credential-domain changes.
- Creation of Agent, Environment, Credential Group, and Session remains explicit.
- Never label recommended or inferred controls as enforced.

---

### Task 1: Capability Contracts

**Files:**

- Modify: `frontend/lib/managed/quickstart-agent-blueprint.ts`
- Create: `frontend/lib/managed/quickstart-capabilities.ts`
- Test: `frontend/lib/managed/quickstart-agent-blueprint.test.ts`
- Test: `frontend/lib/managed/quickstart-capabilities.test.ts`

- [x] Add failing tests for structured Skill, Tool, and MCP recommendations.
- [x] Add failing tests for catalog filtering and runtime evidence.
- [x] Implement normalization and pure capability derivation.
- [x] Run focused unit tests.

### Task 2: Backend Generation Contract

**Files:**

- Modify: `backend/app/joysafeter_api/api/v1/quickstart.py`
- Modify: `backend/tests/test_quickstart_error_contract.py`
- Modify: `frontend/hooks/managed/use-quickstart-chat.ts`
- Modify: `frontend/hooks/managed/use-quickstart-chat.test.tsx`

- [x] Add failing request and tool-schema contract tests.
- [x] Add bounded available-Skill context to requests and prompts.
- [x] Generate actual `skills` and `mcp_servers` configuration fields.
- [x] Filter generated Skill references before Agent creation.
- [x] Run focused backend and hook tests.

### Task 3: Truthful Protection State

**Files:**

- Modify: `frontend/lib/managed/quickstart-outcomes.ts`
- Modify: `frontend/lib/managed/quickstart-outcomes.test.ts`
- Modify: `frontend/hooks/managed/use-quickstart-chat.ts`
- Modify: `frontend/app/managed/quickstart/page.tsx`

- [x] Add failing tests for reviewed-with-gaps protection.
- [x] Track explicit Environment and MCP skips.
- [x] Render an amber completed-with-gaps outcome.
- [x] Verify existing explicit confirmation behavior remains intact.

### Task 4: Capability Plan UI

**Files:**

- Create: `frontend/app/managed/quickstart/components/quickstart-capability-plan.tsx`
- Create: `frontend/app/managed/quickstart/components/quickstart-capability-plan.test.tsx`
- Modify: `frontend/app/managed/quickstart/components/quickstart-agent-blueprint.tsx`
- Modify: `frontend/app/managed/quickstart/page.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [x] Add failing component tests for capability status and Skill selection.
- [x] Fetch the real published Skill catalog in Quickstart.
- [x] Render Skill, Tool, and MCP capability groups before Blueprint details.
- [x] Persist confirmed Skill selections into the Agent create payload.
- [x] Run component and page tests.

### Task 5: Capability Evidence UI

**Files:**

- Create: `frontend/app/managed/quickstart/components/quickstart-capability-evidence.tsx`
- Create: `frontend/app/managed/quickstart/components/quickstart-capability-evidence.test.tsx`
- Modify: `frontend/app/managed/quickstart/page.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [x] Add failing component tests for observed and absent evidence.
- [x] Render evidence derived from session configuration and events.
- [x] Link evidence to Transcript and Debug views.
- [x] Ensure no unobservable enforcement claim is displayed.

### Task 6: Full Verification

**Files:**

- Modify: `docs/superpowers/plans/2026-08-20-quickstart-capability-closure.md`

- [x] Run all Quickstart frontend tests.
- [x] Run backend Quickstart contract tests.
- [x] Run type-check and focused formatting checks.
- [x] Run production build.
- [x] Run Playwright desktop acceptance flow.
- [x] Mark all plan checkboxes complete with evidence.

## Verification Evidence

- `bun run test -- quickstart`: 21 files, 131 tests passed.
- `backend/.venv/bin/pytest backend/tests/test_quickstart_error_contract.py -q`: 20 tests passed; 20 existing SQLAlchemy cycle warnings.
- `bun run type-check`: passed.
- Focused Prettier, Ruff, ESLint, and `git diff --check`: passed with no errors; focused ESLint retains existing import-order and hook-dependency warnings.
- `bun run build`: production build passed and generated `/managed/quickstart`.
- Playwright Chromium fallback at 1440×900: Capability Plan, selected Skill payload, explicit Protect gaps, Secure Launch confirmation, Capability Evidence, tool/MCP observations, no overflow, and zero console/page errors verified.

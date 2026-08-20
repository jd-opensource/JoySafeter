# Quickstart Professional Agent Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-consistent desktop Quickstart that recommends usable runtimes, generates a professional reviewable agent blueprint, communicates progress, presents truthful safety controls, and verifies the first run with acceptance evidence.

**Architecture:** Add pure recommendation and blueprint contracts first, then integrate them into the existing page/hook state machine through focused components. Preserve existing resource APIs while changing the user-facing model from a resource wizard to Understand → Design → Protect → Prove.

**Tech Stack:** Next.js 16, React 19, TypeScript, TanStack Query, Vitest, Testing Library, FastAPI, Pydantic, pytest, Playwright Chromium.

**Spec:** `docs/superpowers/specs/2026-08-20-quickstart-professional-agent-experience-design.md`

## Global Constraints

- No new frontend dependency.
- Desktop web is the target surface.
- Preserve explicit confirmation before resource creation.
- Preserve project scope, read-only, typed-ID, credential, and stream-lifecycle safeguards.
- Work only in Quickstart-related files unless a shared contract must change.

---

### Task 1: Usability-Driven Runtime Recommendation

**Files:**

- Create: `frontend/lib/managed/quickstart-engine-recommendation.ts`
- Create: `frontend/lib/managed/quickstart-engine-recommendation.test.ts`
- Modify: `frontend/app/managed/quickstart/page.tsx`
- Modify: `frontend/app/managed/quickstart/page.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**

- Produces: `recommendQuickstartEngine(options): QuickstartEngineRecommendation | null`
- Produces: readiness labels consumed by the landing runtime chooser.

- [x] Write failing pure ranking tests for usable intent match, usable fallback, and setup-required fallback.
- [x] Run the focused test and confirm the old fixed-priority behavior cannot satisfy it.
- [x] Implement runtime readiness and ranking.
- [x] Add page tests showing `Ready now` and `Setup required` and recommending a usable runtime.
- [x] Integrate active compatible Model Connection counts into the landing recommendation UI.
- [x] Run focused recommendation and page tests.

### Task 2: Professional Agent Blueprint Contract

**Files:**

- Create: `frontend/lib/managed/quickstart-agent-blueprint.ts`
- Create: `frontend/lib/managed/quickstart-agent-blueprint.test.ts`
- Modify: `frontend/lib/managed/quickstart-create.ts`
- Modify: `frontend/lib/managed/quickstart-create.test.ts`
- Modify: `backend/app/joysafeter_api/api/v1/quickstart.py`
- Modify: `backend/tests/test_quickstart_error_contract.py`

**Interfaces:**

- Produces: `QuickstartAgentBlueprint`, `normalizeQuickstartAgentBlueprint`, `quickstartBlueprintMetadata`.
- Backend tool schema emits optional `blueprint` matching the frontend contract.

- [x] Write failing normalization tests for complete, partial, and malformed blueprint output.
- [x] Run the focused tests and confirm failure.
- [x] Implement normalization and metadata compilation.
- [x] Extend agent create-body tests to prove blueprint metadata persists without raw nested values.
- [x] Add backend prompt/tool-schema tests for professional blueprint fields and one-question clarification policy.
- [x] Update the backend prompt and tool schema.
- [x] Run frontend and backend contract tests.

### Task 3: Blueprint Review and Generation Progress

**Files:**

- Create: `frontend/app/managed/quickstart/components/quickstart-agent-blueprint.tsx`
- Create: `frontend/app/managed/quickstart/components/quickstart-agent-blueprint.test.tsx`
- Create: `frontend/app/managed/quickstart/components/quickstart-generation-status.tsx`
- Create: `frontend/app/managed/quickstart/components/quickstart-generation-status.test.tsx`
- Modify: `frontend/hooks/managed/use-quickstart-chat.ts`
- Modify: `frontend/hooks/managed/use-quickstart-chat.test.tsx`
- Modify: `frontend/app/managed/quickstart/page.tsx`
- Modify: `frontend/app/managed/quickstart/page.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**

- Hook produces `generationState`, `cancelGeneration`, and `retryGeneration`.
- Blueprint component consumes normalized blueprint and stream state.

- [x] Write failing component tests for section hierarchy, partial output, and advanced-config fallback.
- [x] Write failing hook tests for cancellation and retry from the last generation request.
- [x] Implement semantic generation state and cancellation.
- [x] Implement Blueprint and Generation Status components.
- [x] Make Blueprint the default right-panel tab; retain YAML/JSON under Advanced.
- [x] Run component, hook, and page tests.

### Task 4: Truthful Safety Plan and Acceptance Run

**Files:**

- Create: `frontend/lib/managed/quickstart-launch-assurance.ts`
- Create: `frontend/lib/managed/quickstart-launch-assurance.test.ts`
- Modify: `frontend/lib/managed/quickstart-trial-status.ts`
- Modify: `frontend/lib/managed/quickstart-trial-status.test.ts`
- Modify: `frontend/app/managed/quickstart/page.tsx`
- Modify: `frontend/app/managed/quickstart/page.test.tsx`
- Modify: `frontend/hooks/managed/use-quickstart-chat.ts`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**

- Produces: explicit launch assurance states and acceptance evidence model.
- Trial status distinguishes response receipt from acceptance confirmation.

- [x] Write failing tests for enforced, recommended, not-authorized, and automatic safety states.
- [x] Write failing tests that a reply becomes `response_received`, not `success`.
- [x] Implement assurance derivation and revised trial states.
- [x] Render acceptance message/checks and truthful launch copy.
- [x] Preserve transcript/debug links as evidence.
- [x] Run focused tests.

### Task 5: Desktop Verification

**Files:**

- Modify only if verification finds defects.

- [x] Run all Quickstart frontend tests.
- [x] Run Quickstart backend contract tests.
- [x] Run frontend type-check for touched contracts.
- [x] Use Playwright Chromium at 1440×900 because the Browser plugin is unavailable.
- [x] Verify landing recommendation, setup-required alternative, generation progress, Blueprint review, safety review, and acceptance-run evidence.
- [x] Inspect final screenshots with `view_image` and repair remaining desktop visual issues.

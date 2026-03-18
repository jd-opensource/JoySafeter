# Boardroom Editorial UI Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the JoySafeter frontend into a boardroom-style enterprise UI without changing application behavior.

**Architecture:** The refactor starts with a shared design system layer in global CSS and common UI primitives, then reworks the application shell and high-traffic page families to consume that system. The highest leverage comes from stabilizing tokens, typography, surface treatments, navigation, and form controls first, then applying them to auth, dashboard, chat, settings, and data-heavy pages.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, Framer Motion, Radix UI, local font assets

---

### Task 1: Establish boardroom design tokens

**Files:**
- Modify: `styles/globals.css`
- Modify: `app/layout.tsx`

**Step 1: Write the failing test**

Document visual acceptance targets for palette, typography, and core surface utilities because this refactor is largely presentational and has limited automated UI coverage.

**Step 2: Run test to verify it fails**

Run: `pnpm build`
Expected: existing build may succeed or fail independently; this step is used to record the current baseline before edits.

**Step 3: Write minimal implementation**

- Replace violet-forward tokens with boardroom neutrals and ink-blue emphasis
- Switch the root layout to local premium typography
- Add shared utility classes for editorial surfaces, section headers, quiet badges, and executive page shells

**Step 4: Run test to verify it passes**

Run: `pnpm build`
Expected: build completes with the new token system in place.

**Step 5: Commit**

```bash
git add app/layout.tsx styles/globals.css docs/plans/2026-03-17-boardroom-editorial-design.md docs/plans/2026-03-17-boardroom-editorial-ui-refactor.md
git commit -m "feat: establish boardroom editorial design system"
```

### Task 2: Rebuild shared primitives and application shell

**Files:**
- Modify: `components/ui/button.tsx`
- Modify: `components/ui/card.tsx`
- Modify: `components/ui/input.tsx`
- Modify: `components/ui/textarea.tsx`
- Modify: `components/ui/select.tsx`
- Modify: `components/ui/table.tsx`
- Modify: `components/app-shell/index.tsx`
- Modify: `components/app-sidebar/app-sidebar.tsx`
- Modify: `components/app-sidebar/app-logo.tsx`
- Modify: `components/app-sidebar/user-info.tsx`

**Step 1: Write the failing test**

Identify any existing component tests that rely on structural output from shared primitives and record the behavior most sensitive to class changes.

**Step 2: Run test to verify it fails**

Run: `pnpm test`
Expected: no new tests yet, but this establishes the current UI component baseline before refactoring shared primitives.

**Step 3: Write minimal implementation**

- Re-skin shared primitives with the boardroom system
- Redesign the sidebar, logo area, and user panel to match the executive navigation language
- Tighten shell backgrounds, padding rhythm, and page transitions

**Step 4: Run test to verify it passes**

Run: `pnpm test`
Expected: existing tests still pass after the shared component refactor.

**Step 5: Commit**

```bash
git add components/ui/button.tsx components/ui/card.tsx components/ui/input.tsx components/ui/textarea.tsx components/ui/select.tsx components/ui/table.tsx components/app-shell/index.tsx components/app-sidebar/app-sidebar.tsx components/app-sidebar/app-logo.tsx components/app-sidebar/user-info.tsx
git commit -m "feat: redesign executive shell and shared primitives"
```

### Task 3: Redesign authentication surfaces

**Files:**
- Modify: `app/(auth)/components/auth-background.tsx`
- Modify: `app/(auth)/layout.tsx`
- Modify: `app/(auth)/signin/login-form.tsx`
- Modify: `app/(auth)/signup/signup-form.tsx`
- Modify: `app/(auth)/reset-password/reset-password-form.tsx`
- Modify: `app/(auth)/verify/verify-content.tsx`

**Step 1: Write the failing test**

Define the expected auth layout structure and preserve form semantics and submit behavior.

**Step 2: Run test to verify it fails**

Run: `pnpm build`
Expected: if any auth layout assumptions break during the refactor, build or type-check will catch them.

**Step 3: Write minimal implementation**

- Remove particles and promotional startup styling
- Create the editorial split-layout with executive brand messaging
- Re-skin all auth forms to use the same input, button, and helper language

**Step 4: Run test to verify it passes**

Run: `pnpm build`
Expected: auth pages compile cleanly with the new layout.

**Step 5: Commit**

```bash
git add app/'(auth)'/components/auth-background.tsx app/'(auth)'/layout.tsx app/'(auth)'/signin/login-form.tsx app/'(auth)'/signup/signup-form.tsx app/'(auth)'/reset-password/reset-password-form.tsx app/'(auth)'/verify/verify-content.tsx
git commit -m "feat: redesign boardroom auth experience"
```

### Task 4: Rework executive dashboard and content pages

**Files:**
- Modify: `app/page.tsx`
- Modify: `app/knowledge/datasets/page.tsx`
- Modify: `app/knowledge/datasets/[datasetId]/page.tsx`
- Modify: `app/settings/models/page.tsx`
- Modify: `app/skills/page.tsx`
- Modify: `app/skills/SkillsManager.tsx`
- Modify: `app/openclaw/page.tsx`
- Modify: `app/openclaw/components/OpenClawManagement.tsx`

**Step 1: Write the failing test**

Capture critical page invariants such as links, controls, search behavior, and layout states that must remain intact after the visual rewrite.

**Step 2: Run test to verify it fails**

Run: `pnpm test`
Expected: current tests provide baseline coverage for page logic before styling changes.

**Step 3: Write minimal implementation**

- Replace marketing-style hero and stat treatments with executive summary modules
- Normalize page headers, toolbar layouts, filters, list shells, and provider cards
- Carry the boardroom visual language through knowledge, skills, settings, and operations pages

**Step 4: Run test to verify it passes**

Run: `pnpm test`
Expected: behavior remains stable across redesigned content pages.

**Step 5: Commit**

```bash
git add app/page.tsx app/knowledge/datasets/page.tsx app/knowledge/datasets/[datasetId]/page.tsx app/settings/models/page.tsx app/skills/page.tsx app/skills/SkillsManager.tsx app/openclaw/page.tsx app/openclaw/components/OpenClawManagement.tsx
git commit -m "feat: redesign executive dashboard and operations pages"
```

### Task 5: Rebuild Copilot and workspace-adjacent surfaces

**Files:**
- Modify: `app/chat/ChatInterface.tsx`
- Modify: `app/chat/components/ChatHome.tsx`
- Modify: `app/chat/components/MessageItem.tsx`
- Modify: `app/chat/components/ThreadContent.tsx`
- Modify: `app/chat/components/ToolExecutionPanel.tsx`
- Modify: `app/chat/components/ToolNavigation.tsx`
- Modify: `app/chat/components/CodeViewer.tsx`
- Modify: `app/workspace/[workspaceId]/components/sidebar/components/workspace-header/workspace-header.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/ApiAccessDialog.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/CopilotDrawer.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/ExecutionModal.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/LoadModal.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/RunInputModal.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/StateVariablePanel.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/copilot/CopilotChat.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/copilot/CopilotInput.tsx`
- Modify: `app/workspace/[workspaceId]/[agentId]/components/execution/ExecutionPanelNew.tsx`

**Step 1: Write the failing test**

Record chat and builder interaction assumptions so visual rewrites do not disrupt composer behavior, panel toggles, or modal flows.

**Step 2: Run test to verify it fails**

Run: `pnpm test`
Expected: current tests validate critical chat and workspace behavior before styling changes.

**Step 3: Write minimal implementation**

- Move Copilot to a disciplined workstation aesthetic
- Unify drawers, execution panels, and builder-adjacent panels with the same editorial surface language
- Improve information hierarchy for thread content, metadata, and tool execution blocks

**Step 4: Run test to verify it passes**

Run: `pnpm test`
Expected: existing chat and workspace behavior remains intact.

**Step 5: Commit**

```bash
git add app/chat/ChatInterface.tsx app/chat/components/ChatHome.tsx app/chat/components/MessageItem.tsx app/chat/components/ThreadContent.tsx app/chat/components/ToolExecutionPanel.tsx app/chat/components/ToolNavigation.tsx app/chat/components/CodeViewer.tsx app/workspace/[workspaceId]/components/sidebar/components/workspace-header/workspace-header.tsx app/workspace/[workspaceId]/[agentId]/components/ApiAccessDialog.tsx app/workspace/[workspaceId]/[agentId]/components/CopilotDrawer.tsx app/workspace/[workspaceId]/[agentId]/components/ExecutionModal.tsx app/workspace/[workspaceId]/[agentId]/components/LoadModal.tsx app/workspace/[workspaceId]/[agentId]/components/RunInputModal.tsx app/workspace/[workspaceId]/[agentId]/components/StateVariablePanel.tsx app/workspace/[workspaceId]/[agentId]/components/copilot/CopilotChat.tsx app/workspace/[workspaceId]/[agentId]/components/copilot/CopilotInput.tsx app/workspace/[workspaceId]/[agentId]/components/execution/ExecutionPanelNew.tsx
git commit -m "feat: redesign copilot and workspace surfaces"
```

### Task 6: Final regression verification

**Files:**
- Modify: any touched files from tasks 1-5

**Step 1: Write the failing test**

Create a verification checklist covering auth, dashboard, navigation, knowledge pages, settings, Copilot, and workspace visual consistency.

**Step 2: Run test to verify it fails**

Run: `pnpm lint && pnpm type-check && pnpm build && pnpm test`
Expected: any remaining regressions or type issues are surfaced here.

**Step 3: Write minimal implementation**

- Fix any regressions from lint, type-check, build, and test output
- Polish spacing and visual inconsistencies uncovered during validation

**Step 4: Run test to verify it passes**

Run: `pnpm lint && pnpm type-check && pnpm build && pnpm test`
Expected: commands exit successfully or produce any pre-existing blockers that must be reported explicitly.

**Step 5: Commit**

```bash
git add .
git commit -m "feat: complete boardroom editorial ui refactor"
```

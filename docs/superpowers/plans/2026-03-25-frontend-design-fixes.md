# Frontend Design Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all design inconsistencies across the JoySafeter frontend, from P0 color unification to P3 Framer Motion micro-interactions.

**Architecture:** Systematic fixes starting with the global design token layer (globals.css, tailwind.config.ts), then propagating through component-level usage, then removing dead assets, then adding motion polish. Each task is self-contained and can be verified visually in a dev server.

**Tech Stack:** Next.js 14 App Router, Tailwind CSS v3, shadcn/ui, Framer Motion v12, CSS custom properties

---

## File Map

| File | Task(s) |
|------|---------|
| `frontend/styles/globals.css` | T1 (surface tokens), T4 (z-index vars) |
| `frontend/components/app-shell/index.tsx` | T2 (sidebar width) |
| `frontend/app/chat/components/ChatHome.tsx` | T3 (brand color), T5 (visual upgrade) |
| `frontend/app/chat/components/ChatInput.tsx` | T3 (brand color) |
| `frontend/app/skills/page.tsx` | T3 (brand color) |
| `frontend/app/chat/components/MessageItem.tsx` | T6 (Framer Motion) |
| `frontend/app/layout.tsx` | T7 (remove unused fonts) |
| `frontend/styles/fonts/season/` | T7 (delete) |
| `frontend/styles/fonts/inter/` | T7 (delete) |
| `frontend/components/ui/dialog.tsx` | T4 (z-index) |

---

## Task 1: Fix Surface Token System (P1)

**Files:**
- Modify: `frontend/styles/globals.css:55-177`

Remove duplicate token values and fill in the missing numbers. The goal: each `--surface-N` should be a distinct value, monotonically increasing in darkness (light mode) / depth (dark mode).

- [ ] **Step 1: Replace the surface token block in `:root`/`.light`**

In `frontend/styles/globals.css`, replace lines 58–70 (the Surfaces block inside `:root, .light`) with:

```css
    /* Surfaces - progressively darker grays */
    --bg: #f4f5f7;
    --surface-1: #f4f5f7;
    --surface-2: #fafbfc;
    --surface-3: #eef0f2;
    --surface-4: #e8eaed;
    --surface-5: #e2e4e8;
    --surface-6: #dcdfe4;
    --surface-7: #d5d8dc;
    --surface-8: #cdd0d6;
    --surface-9: #c6c9cf;
    --surface-10: #bfc2c8;
    --surface-11: #b8bbc1;
    --surface-12: #adb0b7;
    --surface-elevated: #fafbfc;
```

- [ ] **Step 2: Replace the surface token block in `.dark`**

In `frontend/styles/globals.css`, replace lines 121–132 (the Surfaces block inside `.dark`) with:

```css
    /* Surfaces - progressively deeper navy */
    --bg: #0f1419;
    --surface-1: #141a21;
    --surface-2: #1a222b;
    --surface-3: #1f2933;
    --surface-4: #212b36;
    --surface-5: #283341;
    --surface-6: #2e3a4a;
    --surface-7: #334252;
    --surface-8: #3a4a5c;
    --surface-9: #405263;
    --surface-10: #475a6b;
    --surface-11: #4f6273;
    --surface-12: #576a7c;
    --surface-elevated: #1a222b;
```

- [ ] **Step 3: Verify no visual regressions**

Start dev server (`cd frontend && npm run dev`) and check that Chat, Workspace, and Settings pages render correctly with no obvious color breaks.

- [ ] **Step 4: Commit**

```bash
git add frontend/styles/globals.css
git commit -m "fix: repair surface token system - remove duplicates, fill gaps 6-10"
```

---

## Task 2: Fix Sidebar CSS Variable / Actual Width Mismatch (P0)

**Files:**
- Modify: `frontend/styles/globals.css:9`
- Modify: `frontend/components/app-shell/index.tsx:44`

The `--sidebar-width` CSS variable is `256px` but the AppShell renders `w-[140px]`. Align the CSS variable to match the actual rendered width so consuming code can rely on it.

- [ ] **Step 1: Update `--sidebar-width` in globals.css**

In `frontend/styles/globals.css`, line 9, change:
```css
  --sidebar-width: 256px;
```
to:
```css
  --sidebar-width: 140px;
  --sidebar-width-collapsed: 64px;
```

- [ ] **Step 2: Use CSS variable in AppShell**

In `frontend/components/app-shell/index.tsx`, replace lines 41–46:
```tsx
      <div
        className={cn(
          'flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out',
          isAppSidebarCollapsed ? 'w-[64px]' : 'w-[140px]',
        )}
      >
```
with:
```tsx
      <div
        style={{
          width: isAppSidebarCollapsed
            ? 'var(--sidebar-width-collapsed)'
            : 'var(--sidebar-width)',
        }}
        className="flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out"
      >
```

- [ ] **Step 3: Verify sidebar collapses/expands correctly**

Navigate to `/chat` (expanded, 140px) and `/workspace/...` (collapsed, 64px). Confirm transitions work.

- [ ] **Step 4: Commit**

```bash
git add frontend/styles/globals.css frontend/components/app-shell/index.tsx
git commit -m "fix: align --sidebar-width CSS variable with actual rendered sidebar width"
```

---

## Task 3: Unify Primary Action Color (P0)

**Files:**
- Modify: `frontend/app/chat/components/ChatHome.tsx`
- Modify: `frontend/app/chat/components/ChatInput.tsx`
- Modify: `frontend/app/skills/page.tsx`

Replace all hardcoded `blue-600` / `emerald-600` primary action colors with the design system's `--brand-500` / `primary` color. The submit button, "New Skill" button, and agent mode toggle should all share the same visual language.

- [ ] **Step 1: Fix send button in `ChatHome.tsx`**

In `frontend/app/chat/components/ChatHome.tsx`, find the send button around line 521. Replace:
```tsx
                          ? 'bg-blue-600 hover:bg-blue-700'
```
with:
```tsx
                          ? 'bg-primary hover:bg-primary/90'
```

- [ ] **Step 2: Fix agent mode toggle in `ChatHome.tsx`**

In `frontend/app/chat/components/ChatHome.tsx`, find the autoRedirect button around line 422–433. Replace:
```tsx
                        state.autoRedirect
                            ? 'border-emerald-200 text-emerald-600 hover:border-emerald-300 hover:bg-emerald-50'
```
with:
```tsx
                        state.autoRedirect
                            ? 'border-primary/30 text-primary hover:border-primary/50 hover:bg-primary/5'
```

- [ ] **Step 3: Fix drag-over color in `ChatInput.tsx`**

In `frontend/app/chat/components/ChatInput.tsx`, line 143. Replace:
```tsx
          isDragOver && 'border-blue-400 bg-blue-50',
```
with:
```tsx
          isDragOver && 'border-primary/50 bg-primary/5',
```

- [ ] **Step 4: Fix send button in `ChatInput.tsx`**

In `frontend/app/chat/components/ChatInput.tsx`, line 204. Replace:
```tsx
                    ? 'bg-blue-600 hover:bg-blue-700'
```
with:
```tsx
                    ? 'bg-primary hover:bg-primary/90'
```

- [ ] **Step 5: Fix "New Skill" button in `skills/page.tsx`**

In `frontend/app/skills/page.tsx`, line 51. Replace:
```tsx
              className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
```
with:
```tsx
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
```

- [ ] **Step 6: Fix active tab text color in `skills/page.tsx`**

In `frontend/app/skills/page.tsx`, lines 36 and 44. Replace both occurrences of:
```tsx
data-[state=active]:text-emerald-600
```
with:
```tsx
data-[state=active]:text-primary
```

- [ ] **Step 7: Visual check**

Open `/chat` and `/skills`. Verify all primary action buttons are now the same brand color (violet in light mode, sky blue in dark mode). Toggle dark mode and confirm the color shifts correctly.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/chat/components/ChatHome.tsx \
        frontend/app/chat/components/ChatInput.tsx \
        frontend/app/skills/page.tsx
git commit -m "fix: unify primary action color to design system --primary token"
```

---

## Task 4: Fix z-index Strategy (P2)

**Files:**
- Modify: `frontend/styles/globals.css:8-13`
- Modify: `frontend/components/ui/dialog.tsx:25,55`

Replace the `z-[10000000]` magic number with a defined CSS variable.

- [ ] **Step 1: Add z-index variables to `globals.css`**

In `frontend/styles/globals.css`, after the existing `:root` block (after line 13, before `.sidebar-container`), add:

```css
/* Z-index scale */
:root {
  --z-sidebar: 10;
  --z-panel: 20;
  --z-dropdown: 100;
  --z-modal-overlay: 500;
  --z-modal: 501;
  --z-toast: 600;
}
```

- [ ] **Step 2: Update `dialog.tsx` overlay z-index**

In `frontend/components/ui/dialog.tsx`, line 25, replace:
```tsx
        'fixed inset-0 z-[10000000] bg-white/50 ...
```
with:
```tsx
        'fixed inset-0 z-[var(--z-modal-overlay)] bg-white/50 ...
```

- [ ] **Step 3: Update `dialog.tsx` content z-index**

In `frontend/components/ui/dialog.tsx`, line 55, replace:
```tsx
          'fixed left-[50%] top-[50%] z-[10000000] grid ...
```
with:
```tsx
          'fixed left-[50%] top-[50%] z-[var(--z-modal)] grid ...
```

- [ ] **Step 4: Check dialogs still stack above ReactFlow canvas**

Open `/workspace/...`, trigger any dialog (e.g., Run modal). Confirm dialog appears above the canvas nodes.

- [ ] **Step 5: Commit**

```bash
git add frontend/styles/globals.css frontend/components/ui/dialog.tsx
git commit -m "fix: replace z-[10000000] magic number with CSS variable z-index scale"
```

---

## Task 5: Chat Homepage Visual Upgrade (P1)

**Files:**
- Modify: `frontend/app/chat/components/ChatHome.tsx`

The chat home page has a weak visual presence. Upgrade: richer background, stronger heading, better mode card icons with semantic colors.

- [ ] **Step 1: Upgrade the page background and heading**

In `frontend/app/chat/components/ChatHome.tsx`, replace lines 341–348:
```tsx
    <div className="flex h-full w-full bg-gray-50">
      <div className="relative flex flex-1 flex-col items-center justify-center p-8">
        <div className="flex w-full max-w-3xl flex-col gap-8">
          <div className="text-center">
            <h1 className="mb-2 text-4xl font-light tracking-tight text-gray-900">
              {t('chat.createSomethingAwesome')}
            </h1>
          </div>
```
with:
```tsx
    <div className="flex h-full w-full bg-[var(--bg)]">
      <div className="relative flex flex-1 flex-col items-center justify-center p-8">
        {/* Subtle radial gradient ambient */}
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            background:
              'radial-gradient(ellipse 60% 40% at 50% 0%, hsl(var(--primary) / 0.08) 0%, transparent 70%)',
          }}
        />
        <div className="relative flex w-full max-w-3xl flex-col gap-8">
          <div className="text-center">
            <h1 className="mb-2 text-[32px] font-semibold tracking-tight text-[var(--text-primary)]">
              {t('chat.createSomethingAwesome')}
            </h1>
          </div>
```

- [ ] **Step 2: Upgrade the input container**

In `frontend/app/chat/components/ChatHome.tsx`, replace the rounded container class on line 351:
```tsx
            <div className="rounded-2xl border border-gray-200 bg-gray-50 transition-all">
```
with:
```tsx
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] shadow-sm transition-all focus-within:border-[hsl(var(--primary)/0.4)] focus-within:shadow-md">
```

- [ ] **Step 3: Update textarea placeholder color to use token**

In `frontend/app/chat/components/ChatHome.tsx`, find the textarea around line 405–414. Replace:
```tsx
                    className="max-h-[160px] min-h-[44px] w-full resize-none overflow-y-auto border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
```
with:
```tsx
                    className="max-h-[160px] min-h-[44px] w-full resize-none overflow-y-auto border-none bg-transparent text-sm text-[var(--text-primary)] shadow-none placeholder:text-[var(--text-muted)] focus:outline-none focus-visible:ring-0"
```

- [ ] **Step 4: Upgrade mode cards to use semantic surface tokens**

In `frontend/app/chat/components/ChatHome.tsx`, replace the mode card wrapper class on line 576–581:
```tsx
                    className={cn(
                      'group flex cursor-pointer items-start gap-4 overflow-hidden rounded-xl border bg-white p-4 transition-all duration-200',
                      isSelected
                        ? 'border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-100'
                        : 'border-gray-200 hover:border-blue-200 hover:shadow-lg',
                    )}
```
with:
```tsx
                    className={cn(
                      'group flex cursor-pointer items-start gap-4 overflow-hidden rounded-xl border bg-[var(--surface-2)] p-4 transition-all duration-200',
                      isSelected
                        ? 'border-[hsl(var(--primary)/0.5)] bg-[hsl(var(--primary)/0.05)] shadow-md ring-1 ring-[hsl(var(--primary)/0.15)]'
                        : 'border-[var(--border)] hover:border-[hsl(var(--primary)/0.3)] hover:shadow-lg',
                    )}
```

- [ ] **Step 5: Update mode card icon container**

On line 583, replace:
```tsx
                    <div className="rounded-lg border border-blue-100 bg-blue-50 p-2">
```
with:
```tsx
                    <div className="rounded-lg border border-[hsl(var(--primary)/0.2)] bg-[hsl(var(--primary)/0.08)] p-2">
```

- [ ] **Step 6: Update mode card title color**

On lines 591–594, replace:
```tsx
                          isSelected ? 'text-blue-700' : 'text-gray-800 group-hover:text-blue-700',
```
with:
```tsx
                          isSelected ? 'text-primary' : 'text-[var(--text-primary)] group-hover:text-primary',
```

- [ ] **Step 7: Update mode card description**

On line 598, replace:
```tsx
                      <p className="mt-1 text-xs text-gray-500">{mode.description}</p>
```
with:
```tsx
                      <p className="mt-1 text-xs text-[var(--text-muted)]">{mode.description}</p>
```

- [ ] **Step 8: Visual check**

Open `/chat`. The page should have a subtle brand-color glow at top, stronger heading, and input box with a focus ring in brand color when active.

- [ ] **Step 9: Commit**

```bash
git add frontend/app/chat/components/ChatHome.tsx
git commit -m "feat: upgrade Chat homepage - ambient gradient, stronger typography, semantic token colors"
```

---

## Task 6: Remove Unused Font Assets (P2)

**Files:**
- Modify: `frontend/app/layout.tsx` — remove Season Sans and Inter font imports
- Delete: `frontend/styles/fonts/season/` directory
- Delete: `frontend/styles/fonts/inter/` directory

Season Sans is imported in `season.ts` but never passed to the root layout or used in any component. Inter is the same. Both waste bundle size (the woff2 files are included in the build).

- [ ] **Step 1: Verify Season Sans is truly unused**

```bash
grep -r "season\|--font-season" frontend/app frontend/components --include="*.tsx" --include="*.ts" -l
grep -r "inter\|--font-inter" frontend/app frontend/components --include="*.tsx" --include="*.ts" -l
```

Expected: no results in `app/` or `components/` (only results should be the font config files themselves and possibly `app/(auth)/layout.tsx` for soehne — that's fine).

- [ ] **Step 2: Confirm `app/layout.tsx` does not import season or inter**

Read `frontend/app/layout.tsx` — confirm the only font imports are `Geist` and `Geist_Mono`. The `soehne` font is used in `app/(auth)/layout.tsx` directly, which is correct.

- [ ] **Step 3: Delete the Season Sans font directory**

```bash
rm -rf frontend/styles/fonts/season
```

- [ ] **Step 4: Delete the Inter font directory**

```bash
rm -rf frontend/styles/fonts/inter
```

- [ ] **Step 5: Verify build still works**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: successful build, no errors about missing font files.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove unused Season Sans and Inter font assets to reduce bundle size"
```

---

## Task 7: Add Framer Motion Entry Animations to Chat Messages (P3)

**Files:**
- Modify: `frontend/app/chat/components/MessageItem.tsx`

Replace the CSS `animate-in` classes with Framer Motion variants for smoother, more polished message entry.

- [ ] **Step 1: Add framer-motion import to `MessageItem.tsx`**

In `frontend/app/chat/components/MessageItem.tsx`, add after line 6 (`import React...`):
```tsx
import { motion } from 'framer-motion'
```

- [ ] **Step 2: Add animation variants constant (after imports, before SANITIZE_CONFIG)**

```tsx
const messageVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.2, ease: 'easeOut' } },
}
```

- [ ] **Step 3: Replace user message wrapper div with motion.div**

In `frontend/app/chat/components/MessageItem.tsx`, around line 71, replace:
```tsx
    return (
      <div className="mb-6 flex justify-end duration-200 animate-in fade-in slide-in-from-bottom-1">
```
with:
```tsx
    return (
      <motion.div
        className="mb-6 flex justify-end"
        variants={messageVariants}
        initial="hidden"
        animate="visible"
      >
```

And change the closing `</div>` to `</motion.div>`.

- [ ] **Step 4: Replace assistant message wrapper div with motion.div**

Find the assistant message return block (after the `if (isUser)` block). Wrap it similarly:
```tsx
  return (
    <motion.div
      className="mb-6 flex items-start gap-3"
      variants={messageVariants}
      initial="hidden"
      animate="visible"
    >
```

And change its closing `</div>` to `</motion.div>`.

- [ ] **Step 5: Verify messages animate in smoothly**

Open `/chat`, start a conversation, send a message. Both user bubble and assistant response should slide up gently on appearance.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/chat/components/MessageItem.tsx
git commit -m "feat: add Framer Motion entry animations to chat messages"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] `/chat` — brand color send button, ambient gradient, token-based mode cards
- [ ] `/chat` (dark mode) — all surfaces use `--surface-*` tokens, brand color shifts to sky blue
- [ ] `/skills` — "New Skill" button uses `--primary` color
- [ ] `/workspace/...` — sidebar collapses to 64px, dialogs still appear above canvas
- [ ] Chat messages — smooth slide-up animation on entry
- [ ] `npm run build` — no font import errors, no TypeScript errors

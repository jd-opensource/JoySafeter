# Chat Layout & Interaction Alignment Design

## Goal

Align the Chat page's layout structure and interaction patterns with the Skill page by refactoring the sidebar, upgrading mode cards, and redesigning the input area.

## Context

After the visual beautification pass (colors, shadows, animations), the Chat page still has structural and interaction differences from the Skill page:

1. ChatSidebar has ~260 lines of duplicated JSX across 3 conversation groups
2. Sidebar toggle unmounts/mounts the entire panel with no animation (Skill page uses CSS transitions)
3. Mode cards in ChatHome use a simpler design language than SkillCard
4. Input area is oversized (min-h-[100px]/min-h-[120px] textareas) causing bottom overflow; Skill Creator uses a compact gray-bg pill

## Non-Goals

- No search/filter in ChatSidebar (explicitly excluded)
- No changes to Skill page
- No backend changes
- No changes to chat logic, state management, or streaming
- No dark mode
- No mobile/responsive changes
- No unification of ChatHome's inline input with ChatInput component (they remain separate implementations with aligned styling)

---

## Area 1: ChatSidebar Conversation Row Deduplication

**Problem**: `ChatSidebar.tsx` (~560 lines) has 3 nearly identical blocks for todayConvs, monthConvs, olderConvs — each ~130 lines of the same JSX (conversation row + delete dialog).

### Solution

Extract two components into a new file `app/chat/components/ConversationGroup.tsx`:

**`ConversationItem`** (internal, only used by ConversationGroup):
- Props: `conv: Conversation`, `isActive: boolean`, `isCollapsed: boolean`, `onSelect: (threadId: string) => void`, `onDeleteClick: (e: React.MouseEvent, threadId: string, title: string) => void`, `formatTime: (date: string) => string`, `deleteConfirmOpen: boolean`, `conversationToDelete: { threadId: string; title: string } | null`, `onDeleteConfirmChange: (open: boolean) => void`, `onConfirmDelete: () => void`, `onCancelDelete: () => void`
- Renders: icon + title + time + delete button with AlertDialog
- Exact same markup as current rows (lines 204-297), just extracted
- When `isCollapsed` is `true`, renders icon-only mode: hides title, time, and delete button; centers the `MessageSquare` icon
- AlertDialog state is controlled from parent via props (open state driven by `deleteConfirmOpen && conversationToDelete?.threadId === conv.thread_id`)

**Required imports for `ConversationGroup.tsx`**: `MessageSquare`, `Trash2`, `ChevronDown`, `ChevronRight` from `lucide-react`; `AlertDialog`, `AlertDialogAction`, `AlertDialogCancel`, `AlertDialogContent`, `AlertDialogDescription`, `AlertDialogFooter`, `AlertDialogHeader`, `AlertDialogTitle`, `AlertDialogTrigger` from `@/components/ui/alert-dialog`; `cn` from `@/lib/utils`; `useTranslation` from `@/lib/i18n`

**`ConversationGroup`**:
- Props: `label: string`, `conversations: Conversation[]`, `isExpanded: boolean`, `onToggleExpand: () => void`, `isCollapsed: boolean`, `currentThreadId: string | null`, `onSelectConversation: (threadId: string) => void`, `onDeleteClick: (e: React.MouseEvent, threadId: string, title: string) => void`, `formatTime: (date: string) => string`, `maxItems?: number`, `deleteConfirmOpen: boolean`, `conversationToDelete: { threadId: string; title: string } | null`, `onDeleteConfirmChange: (open: boolean) => void`, `onConfirmDelete: () => void`, `onCancelDelete: () => void`
- Renders: collapsible header button + `ConversationItem` list
- `maxItems` used for olderConvs (currently hardcoded `.slice(0, 10)`)

**ChatSidebar after refactor**: ~200 lines — renders header, loading skeleton, empty state, and 3 `<ConversationGroup>` calls with different props. Delete confirmation dialog state (`deleteConfirmOpen`, `conversationToDelete`) stays in ChatSidebar and is passed down as props.

**Initial expand states**: todayConvs starts expanded (`true`), monthConvs starts expanded (`true`), olderConvs starts collapsed (`false`) — matching current behavior from the existing `isTodayCollapsed`, `isThisMonthCollapsed`, `isOlderCollapsed` state variables (inverted because ConversationGroup uses `isExpanded`).

**Files**:
- Create: `frontend/app/chat/components/ConversationGroup.tsx`
- Modify: `frontend/app/chat/components/ChatSidebar.tsx`

---

## Area 2: Sidebar Collapse Animation

**Problem**: `ChatLayout.tsx:323` uses conditional rendering `{state.ui.sidebarVisible && (<ResizablePanel>...)}`. Toggling unmounts the entire sidebar DOM — no animation, loses scroll position.

### Solution

Use `ResizablePanel`'s built-in `collapsible` prop instead of conditional rendering.

**ChatLayout changes** (`ChatLayout.tsx`):

```
// Before: conditional mount/unmount
{state.ui.sidebarVisible && (
  <>
    <ResizablePanel defaultSize={12} minSize={10} maxSize={25} className="transition-all duration-300">
      <ChatSidebar isCollapsed={false} ... />
    </ResizablePanel>
    <ResizableHandle className="w-px bg-gray-200" />
  </>
)}

// After: always rendered, collapsible
<ResizablePanel
  ref={sidebarPanelRef}
  defaultSize={12}
  minSize={10}
  maxSize={25}
  collapsible
  collapsedSize={0}
  onCollapse={() => dispatch({ type: 'SET_SIDEBAR_VISIBLE', visible: false })}
  onExpand={() => dispatch({ type: 'SET_SIDEBAR_VISIBLE', visible: true })}
  className="overflow-hidden transition-all duration-300"
>
  <ChatSidebar isCollapsed={!state.ui.sidebarVisible} ... />
</ResizablePanel>
<ResizableHandle className="w-px bg-gray-200" />
```

**Ref setup**: Add `const sidebarPanelRef = useRef<ImperativePanelHandle>(null)` and import `ImperativePanelHandle` from `react-resizable-panels`.

**Header toggle button** (`ChatLayout.tsx:258`): Change `onClick` from `dispatch({ type: 'TOGGLE_SIDEBAR' })` to programmatic panel control:
```tsx
onClick={() => {
  if (state.ui.sidebarVisible) {
    sidebarPanelRef.current?.collapse()
  } else {
    sidebarPanelRef.current?.expand()
  }
}}
```

**Cmd+B shortcut** (`ChatLayout.tsx:52`): Change from `dispatch({ type: 'TOGGLE_SIDEBAR' })` to:
```tsx
if (state.ui.sidebarVisible) {
  sidebarPanelRef.current?.collapse()
} else {
  sidebarPanelRef.current?.expand()
}
```
Note: The `useEffect` dependency array must include `state.ui.sidebarVisible` and `sidebarPanelRef`.

Key details:
- `collapsedSize={0}` collapses to zero width
- `onCollapse`/`onExpand` callbacks sync state with the panel's collapsed state via `SET_SIDEBAR_VISIBLE`
- `sidebarPanelRef` (`useRef<ImperativePanelHandle>`) allows programmatic collapse/expand
- ChatSidebar's existing `isCollapsed` prop now actually triggers (it was always `false` before) — renders icon-only mode (centers icons, hides titles/timestamps/delete buttons)
- `overflow-hidden` on the panel prevents content overflow during animation
- The `ResizableHandle` is always rendered (it becomes the panel edge when collapsed)
- Note: `react-resizable-panels` uses CSS `flex-basis` for sizing, not width. The `transition-all` class on the panel may or may not produce a smooth animation depending on the library version. If the transition doesn't animate, the panel will still collapse/expand instantly — the functionality is correct either way. Test after implementation.

**Reducer change** (`useChatReducer.ts`):
- Add `SET_SIDEBAR_VISIBLE` action type to `ChatAction`: `| { type: 'SET_SIDEBAR_VISIBLE'; visible: boolean }`
- Add reducer case: `case 'SET_SIDEBAR_VISIBLE': return { ...state, ui: { ...state.ui, sidebarVisible: action.visible } }`
- `TOGGLE_SIDEBAR` remains in the reducer (still used as fallback) but primary toggle now goes through the panel ref

**Files**:
- Modify: `frontend/app/chat/ChatLayout.tsx`
- Modify: `frontend/app/chat/hooks/useChatReducer.ts`

---

## Area 3: Mode Card Beautification

**Problem**: ChatHome mode cards use basic `rounded-xl border p-4` with conditional hover (`hover:border-blue-300 hover:shadow-md`). SkillCard uses `overflow-hidden transition-all duration-200 hover:border-emerald-200 hover:shadow-lg` with a structured icon container.

### Solution

Upgrade ChatHome mode card styling to match SkillCard's design language (adapted for blue brand):

**Card container** (`ChatHome.tsx:644-648`, mode card `className`):

```
// Before:
'group flex cursor-pointer items-start gap-4 rounded-xl border p-4 transition-all',
isSelected
  ? 'border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-100'
  : 'border-gray-200 bg-white hover:border-blue-300 hover:shadow-md'

// After:
'group flex cursor-pointer items-start gap-4 overflow-hidden rounded-xl border bg-white p-4 transition-all duration-200',
isSelected
  ? 'border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-100'
  : 'border-gray-200 hover:border-blue-200 hover:shadow-lg'
```

**Icon container** (`ChatHome.tsx:651-654`, inside each card):

```
// Before:
<div className={cn(
  'rounded-lg p-2 transition-colors',
  isSelected ? 'bg-blue-100' : 'bg-gray-50 group-hover:bg-blue-50',
)}>

// After:
<div className="rounded-lg border border-blue-100 bg-blue-50 p-2">
```

Note: `ModeConfig` in `modeConfig.ts` does NOT have `bgColor`/`iconColor` fields. The current code uses inline conditional classes (`bg-blue-100`/`bg-gray-50`). After this change, all icons use the unified blue brand container regardless of selected state.

**Title**: keep `text-sm font-medium` (already close to SkillCard's `font-semibold`)

**Description**: keep `text-xs text-gray-500` + ensure `line-clamp-2`

**Mode cards section**: `showCases` is already initialized to `true` (in `useChatSession.ts:54`), so no change needed for default expand state.

**Files**:
- Modify: `frontend/app/chat/components/ChatHome.tsx`

---

## Area 4: Input Area Alignment with Skill Creator

**Problem**: ChatInput has `min-h-[100px]` textarea, ChatHome has `min-h-[120px]` textarea, both use `text-base`, heavy padding, and `shadow-md`/`shadow-sm` — far larger than Skill Creator's compact pill. Causes bottom overflow on small viewports.

### Solution

Align Chat input styling with Skill Creator's pattern: gray-bg pill, compact textarea, smaller buttons.

### ConversationPanel input wrapper (`ConversationPanel.tsx:76`)

```
// Before:
<div className="bg-white px-6 py-4 shadow-[0_-4px_24px_-4px_rgba(0,0,0,0.06)]">

// After:
<div className="border-t border-gray-100 bg-white p-4">
```

### ChatInput container (`ChatInput.tsx:132-134`)

```
// Before:
'flex items-end gap-3 rounded-[24px] border border-gray-200 bg-white p-4 shadow-md transition-all',

// After:
'flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 transition-all',
```

### ChatInput textarea (`ChatInput.tsx:157`)

```
// Before:
className="max-h-[200px] min-h-[100px] flex-1 resize-none overflow-y-auto border-none bg-transparent px-0.5 pb-6 pt-4 text-base shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"

// After:
className="max-h-[160px] min-h-[24px] flex-1 resize-none overflow-y-auto border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
```

Note: `px-0.5`, `pb-6`, `pt-4` are intentionally removed — the new container's `px-4 py-3` provides sufficient padding. The textarea no longer needs its own internal padding.

### ChatInput buttons

| Button | Before | After |
|--------|--------|-------|
| Attach (`ChatInput.tsx:162-175`) | `h-10 w-10 rounded-2xl` | `h-8 w-8 rounded-xl` |
| Send (`ChatInput.tsx:186-203`) | `h-10 w-10` | `h-8 w-8` |
| Stop (`ChatInput.tsx:176-184`) | `h-10 w-10` | `h-8 w-8` |

### ChatInput auto-resize cap (`ChatInput.tsx:58`)

```
// Before:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`

// After:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
```

### ChatHome input (explicit before/after)

ChatHome has its own input area (NOT the `ChatInput` component) with a two-level wrapper structure. Changes:

**Outer container** (`ChatHome.tsx:419`):
```
// Before:
<div className="rounded-[24px] border border-gray-200 bg-white shadow-sm transition-all">

// After:
<div className="rounded-2xl border border-gray-200 bg-gray-50 transition-all">
```

**Inner container** (`ChatHome.tsx:420`):
```
// Before:
<div className="flex w-full flex-col gap-2 p-2 pb-3">

// After:
<div className="flex w-full flex-col gap-2 px-4 py-3">
```

**Textarea** (`ChatHome.tsx:480`):
```
// Before:
className="max-h-[240px] min-h-[120px] w-full resize-none overflow-y-auto border-none bg-transparent px-1 pb-14 pt-5 text-base shadow-none transition-all duration-200 placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"

// After:
className="max-h-[160px] min-h-[24px] w-full resize-none overflow-y-auto border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
```

Note: `pb-14` and `pt-5` are removed. The absolutely-positioned bottom buttons (`ChatHome.tsx:484`, `absolute bottom-2 left-1`) will need their position adjusted since the textarea is now shorter. Change to `absolute bottom-1 left-1` or remove absolute positioning if the textarea min-height no longer provides space for them. Test to verify buttons don't overlap text content.

**Buttons** (`ChatHome.tsx:552-609`): Change all `h-10 w-10` to `h-8 w-8` (attach, stop, send buttons).

**Auto-resize cap** (`ChatHome.tsx:137`):
```
// Before:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`

// After:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
```

**Files**:
- Modify: `frontend/app/chat/conversation/ConversationPanel.tsx`
- Modify: `frontend/app/chat/components/ChatInput.tsx`
- Modify: `frontend/app/chat/components/ChatHome.tsx`

---

## Files Affected (Summary)

| File | Areas |
|------|-------|
| `app/chat/components/ConversationGroup.tsx` | 1 (new) |
| `app/chat/components/ChatSidebar.tsx` | 1 |
| `app/chat/ChatLayout.tsx` | 2 |
| `app/chat/hooks/useChatReducer.ts` | 2 |
| `app/chat/components/ChatHome.tsx` | 3, 4 |
| `app/chat/conversation/ConversationPanel.tsx` | 4 |
| `app/chat/components/ChatInput.tsx` | 4 |

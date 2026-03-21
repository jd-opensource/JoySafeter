# Chat Layout & Interaction Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Chat page's layout structure and interaction patterns with the Skill page by refactoring the sidebar, upgrading mode cards, and redesigning the input area.

**Architecture:** Extract duplicated sidebar JSX into a reusable `ConversationGroup` component, replace conditional DOM mount/unmount with `ResizablePanel` collapsible animation, upgrade mode card styling to match SkillCard, and compact the input area to match Skill Creator's gray-bg pill pattern.

**Tech Stack:** Next.js, React, Tailwind CSS, react-resizable-panels, lucide-react, shadcn/ui AlertDialog

**Spec:** `docs/superpowers/specs/2026-03-21-chat-layout-interaction-alignment-design.md`

**Verification:** No test infrastructure exists in frontend. All verification is visual — run `npm run dev` from `frontend/` and check the Chat page in browser.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/app/chat/components/ConversationGroup.tsx` | Create | `ConversationItem` + `ConversationGroup` — extracted sidebar row + group |
| `frontend/app/chat/components/ChatSidebar.tsx` | Modify | Use `ConversationGroup` instead of 3 duplicated blocks |
| `frontend/app/chat/hooks/useChatReducer.ts` | Modify | Add `SET_SIDEBAR_VISIBLE` action |
| `frontend/app/chat/ChatLayout.tsx` | Modify | Collapsible sidebar panel with ref-based toggle |
| `frontend/app/chat/components/ChatHome.tsx` | Modify | Mode card styling + input area compaction |
| `frontend/app/chat/components/ChatInput.tsx` | Modify | Input area compaction |
| `frontend/app/chat/conversation/ConversationPanel.tsx` | Modify | Input wrapper styling |

---

### Task 1: Extract ConversationGroup Component (Area 1)

**Files:**
- Create: `frontend/app/chat/components/ConversationGroup.tsx`
- Modify: `frontend/app/chat/components/ChatSidebar.tsx`

- [ ] **Step 1: Create `ConversationGroup.tsx` with both components**

Create `frontend/app/chat/components/ConversationGroup.tsx`:

```tsx
'use client'

import { MessageSquare, Trash2, ChevronDown, ChevronRight } from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

interface Conversation {
  thread_id: string
  title: string
  updated_at: string
}

interface ConversationItemProps {
  conv: Conversation
  isActive: boolean
  isCollapsed: boolean
  onSelect: (threadId: string) => void
  onDeleteClick: (e: React.MouseEvent, threadId: string, title: string) => void
  formatTime: (date: string) => string
  deleteConfirmOpen: boolean
  conversationToDelete: { threadId: string; title: string } | null
  onDeleteConfirmChange: (open: boolean) => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
}

function ConversationItem({
  conv,
  isActive,
  isCollapsed,
  onSelect,
  onDeleteClick,
  formatTime,
  deleteConfirmOpen,
  conversationToDelete,
  onDeleteConfirmChange,
  onConfirmDelete,
  onCancelDelete,
}: ConversationItemProps) {
  const { t } = useTranslation()

  if (isCollapsed) {
    return (
      <div
        className={cn(
          'flex cursor-pointer items-center justify-center rounded-lg p-2 transition-colors hover:bg-gray-100',
          isActive && 'bg-blue-50',
        )}
        onClick={() => onSelect(conv.thread_id)}
        title={conv.title || t('chat.untitled')}
      >
        <MessageSquare size={16} className={isActive ? 'text-blue-600' : 'text-gray-500'} />
      </div>
    )
  }

  return (
    <div
      className={cn(
        'group flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-gray-100',
        isActive && 'bg-blue-50',
      )}
      onClick={() => onSelect(conv.thread_id)}
    >
      <MessageSquare
        size={16}
        className={cn('flex-shrink-0', isActive ? 'text-blue-600' : 'text-gray-400')}
      />
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'truncate text-sm',
            isActive ? 'font-medium text-blue-600' : 'text-gray-700',
          )}
        >
          {conv.title || t('chat.untitled')}
        </p>
        <p className="text-xs text-gray-400">{formatTime(conv.updated_at)}</p>
      </div>
      <AlertDialog
        open={deleteConfirmOpen && conversationToDelete?.threadId === conv.thread_id}
        onOpenChange={onDeleteConfirmChange}
      >
        <AlertDialogTrigger asChild>
          <button
            className="flex-shrink-0 rounded p-1 opacity-0 transition-opacity hover:bg-gray-200 group-hover:opacity-100"
            onClick={(e) => onDeleteClick(e, conv.thread_id, conv.title)}
          >
            <Trash2 size={14} className="text-gray-400 hover:text-red-500" />
          </button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('chat.deleteConversation')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('chat.deleteConversationConfirm', {
                title: conversationToDelete?.title || t('chat.untitled'),
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={onCancelDelete}>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={onConfirmDelete}
              className="bg-red-500 hover:bg-red-600"
            >
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

interface ConversationGroupProps {
  label: string
  conversations: Conversation[]
  isExpanded: boolean
  onToggleExpand: () => void
  isCollapsed: boolean
  currentThreadId: string | null
  onSelectConversation: (threadId: string) => void
  onDeleteClick: (e: React.MouseEvent, threadId: string, title: string) => void
  formatTime: (date: string) => string
  maxItems?: number
  deleteConfirmOpen: boolean
  conversationToDelete: { threadId: string; title: string } | null
  onDeleteConfirmChange: (open: boolean) => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
}

export default function ConversationGroup({
  label,
  conversations,
  isExpanded,
  onToggleExpand,
  isCollapsed,
  currentThreadId,
  onSelectConversation,
  onDeleteClick,
  formatTime,
  maxItems,
  deleteConfirmOpen,
  conversationToDelete,
  onDeleteConfirmChange,
  onConfirmDelete,
  onCancelDelete,
}: ConversationGroupProps) {
  if (conversations.length === 0) return null

  const displayConversations = maxItems ? conversations.slice(0, maxItems) : conversations

  return (
    <div className="mb-2">
      {!isCollapsed && (
        <button
          className="flex w-full items-center gap-1 px-3 py-1.5 text-xs font-medium text-gray-500 hover:text-gray-700"
          onClick={onToggleExpand}
        >
          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {label}
          <span className="ml-auto text-gray-400">{conversations.length}</span>
        </button>
      )}
      {(isExpanded || isCollapsed) && (
        <div className="space-y-0.5">
          {displayConversations.map((conv) => (
            <ConversationItem
              key={conv.thread_id}
              conv={conv}
              isActive={currentThreadId === conv.thread_id}
              isCollapsed={isCollapsed}
              onSelect={onSelectConversation}
              onDeleteClick={onDeleteClick}
              formatTime={formatTime}
              deleteConfirmOpen={deleteConfirmOpen}
              conversationToDelete={conversationToDelete}
              onDeleteConfirmChange={onDeleteConfirmChange}
              onConfirmDelete={onConfirmDelete}
              onCancelDelete={onCancelDelete}
            />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Refactor ChatSidebar to use ConversationGroup**

In `frontend/app/chat/components/ChatSidebar.tsx`:

**2a.** Add import at top (after other imports):
```tsx
import ConversationGroup from './ConversationGroup'
```

**2b.** Replace the three state variables (lines 81-83):
```tsx
// Before:
const [isTodayCollapsed, setIsTodayCollapsed] = useState(false)
const [isThisMonthCollapsed, setIsThisMonthCollapsed] = useState(true)
const [isOlderCollapsed, setIsOlderCollapsed] = useState(true)

// After:
const [isTodayExpanded, setIsTodayExpanded] = useState(true)
const [isThisMonthExpanded, setIsThisMonthExpanded] = useState(false)
const [isOlderExpanded, setIsOlderExpanded] = useState(false)
```

**2c.** Replace the entire conversation list section (the three groups of todayConvs, monthConvs, olderConvs — approximately lines 185-535) with:

```tsx
<ConversationGroup
  label={t('chat.today')}
  conversations={todayConvs}
  isExpanded={isTodayExpanded}
  onToggleExpand={() => setIsTodayExpanded(!isTodayExpanded)}
  isCollapsed={isCollapsed}
  currentThreadId={currentThreadId}
  onSelectConversation={onSelectConversation}
  onDeleteClick={handleDeleteConversation}
  formatTime={formatTime}
  deleteConfirmOpen={deleteConfirmOpen}
  conversationToDelete={conversationToDelete}
  onDeleteConfirmChange={setDeleteConfirmOpen}
  onConfirmDelete={handleConfirmDelete}
  onCancelDelete={handleCancelDelete}
/>
<ConversationGroup
  label={t('chat.thisMonth')}
  conversations={monthConvs}
  isExpanded={isThisMonthExpanded}
  onToggleExpand={() => setIsThisMonthExpanded(!isThisMonthExpanded)}
  isCollapsed={isCollapsed}
  currentThreadId={currentThreadId}
  onSelectConversation={onSelectConversation}
  onDeleteClick={handleDeleteConversation}
  formatTime={formatTime}
  deleteConfirmOpen={deleteConfirmOpen}
  conversationToDelete={conversationToDelete}
  onDeleteConfirmChange={setDeleteConfirmOpen}
  onConfirmDelete={handleConfirmDelete}
  onCancelDelete={handleCancelDelete}
/>
<ConversationGroup
  label={t('chat.older')}
  conversations={olderConvs}
  isExpanded={isOlderExpanded}
  onToggleExpand={() => setIsOlderExpanded(!isOlderExpanded)}
  isCollapsed={isCollapsed}
  currentThreadId={currentThreadId}
  onSelectConversation={onSelectConversation}
  onDeleteClick={handleDeleteConversation}
  formatTime={formatTime}
  maxItems={10}
  deleteConfirmOpen={deleteConfirmOpen}
  conversationToDelete={conversationToDelete}
  onDeleteConfirmChange={setDeleteConfirmOpen}
  onConfirmDelete={handleConfirmDelete}
  onCancelDelete={handleCancelDelete}
/>
```

**2d.** Remove unused imports that were only used by the inlined conversation rows: `MessageSquare`, `Trash2`, `ChevronDown`, `ChevronRight` (if no longer referenced elsewhere in the file), and remove all `AlertDialog*` imports.

**2e.** The existing `handleDeleteConversation` handler (line 101) is kept as-is. Add two new handlers for confirm/cancel if they don't exist:

```tsx
const handleConfirmDelete = async () => {
  if (conversationToDelete) {
    await deleteConversation(conversationToDelete.threadId)
  }
  setDeleteConfirmOpen(false)
  setConversationToDelete(null)
}

const handleCancelDelete = () => {
  setDeleteConfirmOpen(false)
  setConversationToDelete(null)
}
```

Check the existing code — if `handleConfirmDelete` already exists with this logic inline in the AlertDialog, extract it. If `handleCancelDelete` logic is inline, extract it too.

- [ ] **Step 3: Visual verification**

Run: `cd frontend && npm run dev`

Check:
- Sidebar shows three conversation groups (Today, This Month, Older)
- Clicking group headers expands/collapses them
- Today and This Month start expanded, Older starts collapsed
- Conversation rows show icon, title, time, delete button on hover
- Delete confirmation dialog works
- Active conversation is highlighted in blue

- [ ] **Step 4: Commit**

```bash
git add frontend/app/chat/components/ConversationGroup.tsx frontend/app/chat/components/ChatSidebar.tsx
git commit -m "refactor: extract ConversationGroup component from ChatSidebar to deduplicate conversation row JSX"
```

---

### Task 2: Sidebar Collapse Animation (Area 2)

**Files:**
- Modify: `frontend/app/chat/hooks/useChatReducer.ts`
- Modify: `frontend/app/chat/ChatLayout.tsx`

- [ ] **Step 1: Add `SET_SIDEBAR_VISIBLE` action to reducer**

In `frontend/app/chat/hooks/useChatReducer.ts`:

**1a.** Add to the `ChatAction` type union (near line 95 where other actions are defined):
```tsx
| { type: 'SET_SIDEBAR_VISIBLE'; visible: boolean }
```

**1b.** Add reducer case (near `TOGGLE_SIDEBAR` case around line 266):
```tsx
case 'SET_SIDEBAR_VISIBLE':
  return { ...state, ui: { ...state.ui, sidebarVisible: action.visible } }
```

- [ ] **Step 2: Refactor ChatLayout sidebar to use collapsible panel**

In `frontend/app/chat/ChatLayout.tsx`:

**2a.** Update imports — add `ImperativePanelHandle` from `react-resizable-panels` and `useRef` is already imported:
```tsx
// Before (line 8):
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'

// After:
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import type { ImperativePanelHandle } from 'react-resizable-panels'
```

**2b.** Add panel ref after other refs (around line 44):
```tsx
const sidebarPanelRef = useRef<ImperativePanelHandle>(null)
```

**2c.** Replace the Cmd+B shortcut handler (lines 48-57):
```tsx
// Before:
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
      e.preventDefault()
      dispatch({ type: 'TOGGLE_SIDEBAR' })
    }
  }
  window.addEventListener('keydown', handleKeyDown)
  return () => window.removeEventListener('keydown', handleKeyDown)
}, [dispatch])

// After:
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
      e.preventDefault()
      if (state.ui.sidebarVisible) {
        sidebarPanelRef.current?.collapse()
      } else {
        sidebarPanelRef.current?.expand()
      }
    }
  }
  window.addEventListener('keydown', handleKeyDown)
  return () => window.removeEventListener('keydown', handleKeyDown)
}, [state.ui.sidebarVisible])
```

**2d.** Replace the header toggle button onClick (line 258):
```tsx
// Before:
onClick={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}

// After:
onClick={() => {
  if (state.ui.sidebarVisible) {
    sidebarPanelRef.current?.collapse()
  } else {
    sidebarPanelRef.current?.expand()
  }
}}
```

**2e.** Replace the sidebar panel section (lines 322-341):
```tsx
// Before:
{state.ui.sidebarVisible && (
  <>
    <ResizablePanel
      defaultSize={12}
      minSize={10}
      maxSize={25}
      className="transition-all duration-300"
    >
      <ChatSidebar
        isCollapsed={false}
        onToggle={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
        onSelectConversation={handleSelectConversation}
        currentThreadId={state.threadId}
        onNewChat={handleNewChat}
      />
    </ResizablePanel>
    <ResizableHandle className="w-px bg-gray-200" />
  </>
)}

// After:
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
  <ChatSidebar
    isCollapsed={!state.ui.sidebarVisible}
    onToggle={() => {
      if (state.ui.sidebarVisible) {
        sidebarPanelRef.current?.collapse()
      } else {
        sidebarPanelRef.current?.expand()
      }
    }}
    onSelectConversation={handleSelectConversation}
    currentThreadId={state.threadId}
    onNewChat={handleNewChat}
  />
</ResizablePanel>
<ResizableHandle className="w-px bg-gray-200" />
```

- [ ] **Step 3: Visual verification**

Run: `cd frontend && npm run dev`

Check:
- Sidebar toggle button collapses/expands the sidebar
- Cmd+B shortcut works
- Sidebar animates (or at least doesn't flash/unmount)
- When collapsed, sidebar takes zero width
- ResizableHandle remains visible as panel edge
- Sidebar isCollapsed prop now triggers icon-only mode in ChatSidebar (if collapsed while visible)

- [ ] **Step 4: Commit**

```bash
git add frontend/app/chat/hooks/useChatReducer.ts frontend/app/chat/ChatLayout.tsx
git commit -m "feat: replace sidebar mount/unmount with ResizablePanel collapsible animation"
```

---

### Task 3: Mode Card Beautification (Area 3)

**Files:**
- Modify: `frontend/app/chat/components/ChatHome.tsx`

- [ ] **Step 1: Update mode card container className**

In `frontend/app/chat/components/ChatHome.tsx`, find the mode card `className` (around line 644-648):

```tsx
// Before:
'group flex cursor-pointer items-start gap-4 rounded-xl border p-4 transition-all',
isSelected
  ? 'border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-100'
  : 'border-gray-200 bg-white hover:border-blue-300 hover:shadow-md',

// After:
'group flex cursor-pointer items-start gap-4 overflow-hidden rounded-xl border bg-white p-4 transition-all duration-200',
isSelected
  ? 'border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-100'
  : 'border-gray-200 hover:border-blue-200 hover:shadow-lg',
```

- [ ] **Step 2: Update icon container className**

Find the icon container inside each card (around line 651-654):

```tsx
// Before:
<div className={cn(
  'rounded-lg p-2 transition-colors',
  isSelected ? 'bg-blue-100' : 'bg-gray-50 group-hover:bg-blue-50',
)}>

// After:
<div className="rounded-lg border border-blue-100 bg-blue-50 p-2">
```

- [ ] **Step 3: Visual verification**

Run: `cd frontend && npm run dev`

Navigate to Chat home page. Check:
- Mode cards have smooth `duration-200` hover transition
- Hover shows `shadow-lg` and `border-blue-200` (softer than before)
- Icon containers are uniformly blue (`bg-blue-50` with `border-blue-100`) regardless of selected state
- Selected card still shows blue ring and blue background
- Cards have `overflow-hidden`

- [ ] **Step 4: Commit**

```bash
git add frontend/app/chat/components/ChatHome.tsx
git commit -m "style: upgrade mode card styling to match SkillCard design language"
```

---

### Task 4: Input Area Alignment (Area 4)

**Files:**
- Modify: `frontend/app/chat/conversation/ConversationPanel.tsx`
- Modify: `frontend/app/chat/components/ChatInput.tsx`
- Modify: `frontend/app/chat/components/ChatHome.tsx`

- [ ] **Step 1: Update ConversationPanel input wrapper**

In `frontend/app/chat/conversation/ConversationPanel.tsx` line 76:

```tsx
// Before:
<div className="bg-white px-6 py-4 shadow-[0_-4px_24px_-4px_rgba(0,0,0,0.06)]">

// After:
<div className="border-t border-gray-100 bg-white p-4">
```

- [ ] **Step 2: Update ChatInput container**

In `frontend/app/chat/components/ChatInput.tsx` line 134:

```tsx
// Before:
'flex items-end gap-3 rounded-[24px] border border-gray-200 bg-white p-4 shadow-md transition-all',

// After:
'flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 transition-all',
```

- [ ] **Step 3: Update ChatInput textarea**

In `frontend/app/chat/components/ChatInput.tsx` line 157:

```tsx
// Before:
className="max-h-[200px] min-h-[100px] flex-1 resize-none overflow-y-auto border-none bg-transparent px-0.5 pb-6 pt-4 text-base shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"

// After:
className="max-h-[160px] min-h-[24px] flex-1 resize-none overflow-y-auto border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
```

- [ ] **Step 4: Update ChatInput buttons**

In `frontend/app/chat/components/ChatInput.tsx`:

Attach button (line 169): change `h-10 w-10 rounded-2xl` to `h-8 w-8 rounded-xl`
Stop button (line 180): change `h-10 w-10` to `h-8 w-8`
Send button (line 191): change `h-10 w-10` to `h-8 w-8`

- [ ] **Step 5: Update ChatInput auto-resize cap**

In `frontend/app/chat/components/ChatInput.tsx` line 58:

```tsx
// Before:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`

// After:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
```

- [ ] **Step 6: Update ChatHome input outer container**

In `frontend/app/chat/components/ChatHome.tsx` around line 419:

```tsx
// Before:
<div className="rounded-[24px] border border-gray-200 bg-white shadow-sm transition-all">

// After:
<div className="rounded-2xl border border-gray-200 bg-gray-50 transition-all">
```

- [ ] **Step 7: Update ChatHome input inner container**

In `frontend/app/chat/components/ChatHome.tsx` around line 420:

```tsx
// Before:
<div className="flex w-full flex-col gap-2 p-2 pb-3">

// After:
<div className="flex w-full flex-col gap-2 px-4 py-3">
```

- [ ] **Step 8: Update ChatHome textarea**

In `frontend/app/chat/components/ChatHome.tsx` around line 480:

```tsx
// Before:
className="max-h-[240px] min-h-[120px] w-full resize-none overflow-y-auto border-none bg-transparent px-1 pb-14 pt-5 text-base shadow-none transition-all duration-200 placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"

// After:
className="max-h-[160px] min-h-[24px] w-full resize-none overflow-y-auto border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
```

- [ ] **Step 9: Update ChatHome bottom buttons position**

In `frontend/app/chat/components/ChatHome.tsx` around line 484, the absolutely-positioned buttons container:

```tsx
// Before:
absolute bottom-2 left-1

// After:
absolute bottom-1 left-1
```

- [ ] **Step 10: Update ChatHome buttons size**

In `frontend/app/chat/components/ChatHome.tsx` (lines 552-609), change all button sizes:

All `h-10 w-10` → `h-8 w-8` (attach, stop, send buttons)

- [ ] **Step 11: Update ChatHome auto-resize cap**

In `frontend/app/chat/components/ChatHome.tsx` around line 137:

```tsx
// Before:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`

// After:
textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
```

- [ ] **Step 12: Visual verification**

Run: `cd frontend && npm run dev`

Check Chat home page:
- Input area uses gray background (`bg-gray-50`)
- Input is compact — no oversized textarea
- Buttons are smaller (`h-8 w-8`)
- No bottom overflow on small viewports
- Text is `text-sm` (not `text-base`)
- Bottom buttons don't overlap text content

Check Chat conversation page:
- Input wrapper has subtle `border-t` instead of heavy shadow
- Input container matches home page styling
- Textarea starts small and grows with content up to 160px max

- [ ] **Step 13: Commit**

```bash
git add frontend/app/chat/conversation/ConversationPanel.tsx frontend/app/chat/components/ChatInput.tsx frontend/app/chat/components/ChatHome.tsx
git commit -m "style: compact input area to match Skill Creator pattern"
```

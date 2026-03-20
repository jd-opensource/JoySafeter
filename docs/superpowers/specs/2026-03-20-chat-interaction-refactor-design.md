# Chat Interaction Refactor Design

Date: 2026-03-20
Status: Draft

## Problem Statement

The current Chat implementation has a significantly inferior interaction experience compared to the Skill Creator. Key gaps:

1. **No guided entry** — users face a blank input box after selecting a mode
2. **Opaque tool calls** — raw tool names (`execute_code`, `write_file`) shown as badges, unintelligible to users
3. **Passive artifact viewing** — Artifacts Drawer requires manual click to open, not proactive
4. **No per-message actions** — only global Send/Stop, no Copy/Retry/Continue on individual messages
5. **Monolithic architecture** — `ChatInterface.tsx` is 700+ lines with 14 `useState` calls, mixing layout, logic, and state

## Goals

- Bring Skill Creator's proven interaction patterns into Chat while preserving free-form conversation
- Establish a shared component library so both Chat and Skill Creator maintain consistent UX
- Refactor Chat architecture to support future interaction enhancements
- Execute in two phases: architecture cleanup first, then interaction enhancement

## Non-Goals

- Converting Chat into a wizard/step-by-step flow
- Building a plugin system for arbitrary mode customization
- Rewriting the backend streaming protocol
- Unifying Skill Creator's streaming logic with Chat's (Skill Creator has its own inline SSE handler with domain-specific interceptions like `preview_skill` parsing; this remains separate)

---

## Architecture Overview

### Existing State to Account For

`ChatInterface.tsx` currently has 14 `useState` calls: `messages`, `localChatId`, `input`, `submitting`, `artifactDrawerOpen`, `sidebarVisible`, `toolPanelOpen`, `selectedTool`, `showNoDefaultModelNotice`, `currentMode`, `hasShownApkPrompt`, `currentGraphId`, plus derived state via `useRef`.

Additionally, `useChatSession.ts` already implements a `useReducer`-based state for `ChatHome` (managing `input`, `files`, `mode`, `selectedAgentId`, `autoRedirect`, `isRedirecting`, `showCases`, `isUploading`). The new `useChatReducer` absorbs the conversation-related concerns; `useChatSession` is retained for `ChatHome`'s landing-screen-only form state (mode selection, agent picker, auto-redirect toggle). The boundary: `useChatSession` owns pre-conversation state, `useChatReducer` owns active-conversation state. `ChatHome.onStartChat()` dispatches to `useChatReducer` to transition.

The `chat/services/` directory (`chatModeService.ts`, `copilotRedirectService.ts`, `graphResolutionService.ts`, `modeHandlers/*`) remains untouched. These services are called by `ChatHome` and `ConversationPanel` as before; they do not depend on state management internals.

### Target Structure

All paths below are relative to `frontend/app/`.

Note: `conversation/`, `preview/`, `hooks/` directories under `chat/` are plain directories (no `page.tsx`), so Next.js App Router will not treat them as route segments.

```
chat/
├── ChatPage.tsx                    # Route entry, passes chatId only
├── ChatLayout.tsx                  # Layout skeleton: sidebar | conversation | preview
├── ChatProvider.tsx                # Context + useReducer unified state
│
├── conversation/
│   ├── ConversationPanel.tsx       # Message list + input container
│   ├── MessageList.tsx             # Evolved from ThreadContent
│   ├── MessageBubble.tsx           # Evolved from MessageItem
│   └── ChatInput.tsx              # Retained, minor adjustments
│
├── preview/
│   ├── PreviewPanel.tsx            # Preview container, tab-based content switching
│   ├── FileTreePreview.tsx         # File tree + code preview (reuses ArtifactPanel logic)
│   └── PreviewTrigger.ts          # Rules for when to auto-expand preview
│
└── hooks/
    ├── useChatReducer.ts           # Replaces 12+ useState
    ├── useBackendChatStream.ts     # Retained, adapted to dispatch
    ├── usePreviewState.ts          # Preview panel state
    └── useFileUpload.ts            # Retained

shared/                              # Located at frontend/app/shared/ (not a route, no page.tsx)
├── ToolCallDisplay/
│   ├── ToolCallBadge.tsx           # Human-readable tool call display
│   ├── ToolCallDetail.tsx          # Tool detail panel (generalized from ToolExecutionPanel)
│   └── toolDisplayRegistry.ts     # Tool name → human-readable label registry
├── StreamingContent/
│   ├── StreamingText.tsx           # Streaming text rendering + cursor animation
│   └── StreamingProgress.tsx       # Step-by-step progress indicator
├── ActionBar/
│   ├── ActionBar.tsx               # Per-message action button container
│   └── actions/                    # Copy, Retry, Regenerate concrete actions
└── StarterPrompts/
    └── StarterPrompts.tsx          # Guided start with configurable prompt list
```

### State Management

Replace 14 `useState` with a single `useReducer` + Context:

```typescript
interface ChatState {
  messages: Message[]
  threadId: string | null
  input: string
  streaming: {
    isProcessing: boolean
    isSubmitting: boolean        // optimistic "thinking" before SSE starts
    text: string
    nodeExecutionLog: any[]      // accumulated across events within a request
  }
  preview: {
    visible: boolean
    fileTree: Record<string, FileInfo>
    activeFile: string | null
  }
  ui: {
    sidebarVisible: boolean
    toolDetailOpen: boolean
    selectedTool: ToolCall | null
    showNoDefaultModelNotice: boolean
  }
  mode: {
    currentMode: string | undefined
    currentGraphId: string | null
    hasShownApkPrompt: boolean   // mode-specific UX flag, reset on mode change
  }
}

type ChatAction =
  // Thread
  | { type: 'SET_THREAD'; threadId: string }
  | { type: 'RESET' }
  // Messages
  | { type: 'APPEND_MESSAGE'; message: Message }
  | { type: 'UPDATE_MESSAGE'; id: string; patch: Partial<Message> }
  | { type: 'SET_MESSAGES'; messages: Message[] }
  // Input
  | { type: 'SET_INPUT'; value: string }
  // Streaming lifecycle
  | { type: 'STREAM_START' }
  | { type: 'STREAM_CONTENT'; delta: string }
  | { type: 'STREAM_DONE' }
  | { type: 'STREAM_ERROR'; error: string }
  // File & tool events
  | { type: 'FILE_EVENT'; path: string; info: FileInfo }
  | { type: 'TOOL_START'; tool: ToolCall }
  | { type: 'TOOL_END'; id: string; result: string }
  // Node execution (agent mode)
  | { type: 'NODE_START'; nodeId: string; label: string }
  | { type: 'NODE_END'; nodeId: string }
  | { type: 'NODE_LOG'; entry: any }  // command, route_decision, loop_iteration, parallel_task, state_update
  // UI toggles
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'TOGGLE_PREVIEW' }
  | { type: 'SELECT_TOOL'; tool: ToolCall | null }
  | { type: 'DISMISS_MODEL_NOTICE' }
  // Mode
  | { type: 'SET_MODE'; mode: string; graphId: string | null }
  | { type: 'SET_APK_PROMPT_SHOWN' }
```

**Performance note**: To avoid streaming deltas re-rendering the entire tree, `ChatProvider` splits into two contexts:
- `ChatStateContext` — full state (low-frequency: messages, UI, mode)
- `ChatStreamContext` — streaming-specific state (high-frequency: `streaming.text`, `streaming.isProcessing`)

Components subscribe only to the context they need. `MessageList` uses `ChatStateContext`; the streaming cursor/indicator uses `ChatStreamContext`.

---

## Shared Component Library

### 1. ToolCallDisplay — Human-Readable Tool Calls

**Registry pattern** for extensible tool name mapping:

```typescript
interface ToolDisplayConfig {
  label: string
  icon?: React.ReactNode
  formatArgs?: (args: any) => string   // Short summary, e.g. "main.py"
  formatDetail?: (args: any) => string // Extended detail string (migrated from toolDisplayUtils.ts's detail field)
  category: 'file' | 'code' | 'search' | 'network' | 'other'
}

// Built-in mappings
const defaultRegistry: Record<string, ToolDisplayConfig> = {
  'write_file':    { label: 'Writing file',    category: 'file',   formatArgs: a => a.path },
  'read_file':     { label: 'Reading file',    category: 'file',   formatArgs: a => a.path },
  'execute_code':  { label: 'Executing code',  category: 'code' },
  'web_search':    { label: 'Searching web',   category: 'search' },
  'preview_skill': { label: 'Deploying skill', category: 'other',  formatArgs: a => a.skill_name },
}

// Modules can extend
registry.register('custom_tool', { label: 'Custom Action', category: 'other' })
```

`ToolCallBadge` renders in compact mode (inline in messages) and expanded mode (detail panel). Replaces current raw tool name badges with human-readable labels + progress indicator.

### 2. StreamingContent — Enhanced Streaming Feedback

`StreamingProgress` converts `node_start`/`node_end` SSE events into visible step progress:

```typescript
interface StepInfo {
  id: string
  label: string
  status: 'pending' | 'active' | 'done'
  startTime?: number
}
```

Rendering logic:
- 4 steps or fewer: horizontal step bar
- More than 4 steps: vertical timeline showing current step +/- 1

Serves both Chat agent mode (already has `node_start`/`node_end` events) and Skill Creator.

### 3. ActionBar — Per-Message Actions

Appears at the bottom of assistant messages:

```typescript
interface ActionBarProps {
  messageId: string
  actions: ActionConfig[]
  layout: 'inline' | 'floating'
}
```

Chat actions: Copy, Retry, Continue (last message only).
Skill Creator actions: Copy, Regenerate, Save to Library (when valid).

Interaction: hidden by default, fade in on hover. Last assistant message always shows actions.

### 4. StarterPrompts — Guided Start

Each mode registers its own starter prompts via `modeConfig`:

```typescript
interface ModeConfig {
  // ... existing fields
  starterPrompts?: StarterPrompt[]
}
```

Click fills the input (does not auto-submit), allowing user modification before sending. On click: input receives focus, cursor positions at end, the clicked chip gets a brief highlight animation as visual feedback.

---

## Layout Refactoring

### Current Layout is Overlay-Based

The current tool and artifact panels are absolutely-positioned floating overlays with fixed width (`SIDE_PANEL_WIDTH = 600`), not part of the `ResizablePanelGroup`. Migrating to a three-column `ResizablePanel` layout is a **breaking layout change** — the transition from overlay to grid requires restructuring the DOM hierarchy, not just swapping components.

### Three-Column Layout

```
┌──────────┬────────────────────┬─────────────┐
│ Sidebar  │   Conversation     │   Preview   │
│          │  ┌──────────────┐  │  ┌─────────┐│
│          │  │ Message List  │  │  │File Tree││
│          │  │ · Readable    │  │  │         ││
│          │  │   tool calls  │  │  ├─────────┤│
│          │  │ · Progress    │  │  │Code View││
│          │  │ · Actions     │  │  │         ││
│          │  ├──────────────┤  │  │         ││
│          │  │ Input         │  │  │         ││
│          │  └──────────────┘  │  └─────────┘│
└──────────┴────────────────────┴─────────────┘
```

The preview panel is a first-class layout citizen using `ResizablePanel`, not an afterthought drawer. Users can drag to resize.

### Preview Panel

Tab-based container switching between file preview and tool detail:

- **Files tab**: appears when `fileTree` has entries, shows hierarchical file browser + code viewer
- **Tool tab**: appears when user clicks a tool call badge, shows tool input/output detail

### Auto-Expand Rules (PreviewTrigger)

`PreviewTrigger` is a **custom hook** (`usePreviewTrigger`) consumed by `ChatLayout`. It subscribes to `ChatStreamContext` and dispatches `TOGGLE_PREVIEW` actions to the reducer.

```typescript
const defaultRules: TriggerRule[] = [
  { event: 'file_event',  action: 'show',  tab: 'files' },
  { event: 'tool_click',  action: 'show',  tab: 'tool' },
  { event: 'stream_done', action: 'hide',
    condition: (state: ChatState) => Object.keys(state.preview.fileTree).length === 0 },
]
```

**Manual override behavior**: When the user manually closes the preview panel, a `userDismissed` flag is set for the current streaming session. Auto-expand rules are suppressed while this flag is active. The flag resets on the next user message submission (new streaming session starts).

User can always manually close/reopen. On screens < 768px, preview falls back to overlay mode.

### Skill Creator Migration

After shared components are established:

```
SkillPreviewPanel (dedicated) → PreviewPanel (shared) + SkillValidation (dedicated slot)
toolDisplayUtils.ts → shared toolDisplayRegistry
```

---

## Implementation Strategy

### Phase 1: Architecture Cleanup (No Visible Changes)

| Step | Action | Deliverable | Verification |
|------|--------|-------------|-------------|
| 1 | Create `useChatReducer.ts` | State reducer + ChatProvider context | 1:1 mapping of all existing useState, TypeScript strict types |
| 2 | Extract `ChatLayout.tsx` | Layout skeleton | Render output identical |
| 3 | Extract `ConversationPanel.tsx` | Message list + input container | Send messages, streaming works |
| 4 | Adapt sidebar to Context | ChatSidebar reads from Context | Switch conversations works |
| 5 | Adapt `useBackendChatStream` | dispatch-based event handling | Full streaming flow works |
| 6 | Wrap tool/artifact panels | `PreviewPanel.tsx` with old logic | Click tool/file still works |

**Completion criteria**: `ChatInterface.tsx` is renamed to `ChatPage.tsx` (the route entry) and reduced to < 50 lines — it renders `ChatProvider` wrapping `ChatLayout`, nothing more. The current `page.tsx` is updated to import from `ChatPage`. All existing functionality unchanged.

### Phase 2: Interaction Enhancement (Visible Improvements)

Each step is independently deliverable:

| Step | Feature | Files Changed | Dependencies |
|------|---------|---------------|-------------|
| 1 | Tool call readability | new `shared/ToolCallDisplay/*`, modify `MessageBubble` | None |
| 2 | Persistent preview panel | new `preview/*`, modify `ChatLayout`, delete `ArtifactsDrawer` + `CompactArtifactStatus` | Phase 1 layout split |
| 3 | Per-message action buttons | new `shared/ActionBar/*`, modify `MessageBubble` | None |
| 4 | Starter prompts | new `shared/StarterPrompts/`, modify `modeConfig`, `ChatHome` | None |
| 5 | Skill Creator migration | modify `skills/creator/*` to use shared components | Steps 1, 2 |

### File Change Summary

**New (~15 files)**:
- `shared/ToolCallDisplay/` (3 files)
- `shared/StreamingContent/` (2 files)
- `shared/ActionBar/` (3 files)
- `shared/StarterPrompts/` (1 file)
- `chat/ChatLayout.tsx`
- `chat/ChatProvider.tsx`
- `chat/conversation/ConversationPanel.tsx`
- `chat/preview/PreviewPanel.tsx`, `FileTreePreview.tsx`, `PreviewTrigger.ts`
- `chat/hooks/useChatReducer.ts`, `usePreviewState.ts`

**Modified (~8 files)**:
- `chat/ChatInterface.tsx` — renamed to `ChatPage.tsx`, reduced to Provider + Layout glue (< 50 lines)
- `chat/components/MessageItem.tsx` → moved to `chat/conversation/MessageBubble.tsx`, integrates new components
- `chat/components/ThreadContent.tsx` → moved to `chat/conversation/MessageList.tsx`, simplified
- `chat/hooks/useBackendChatStream.ts` — adapted to dispatch (note: `nodeExecutionLog` moves from closure variable to `ChatState.streaming.nodeExecutionLog`, accumulated via `NODE_LOG` actions)
- `chat/config/modeConfig.ts` — add `starterPrompts` field
- `chat/components/ChatHome.tsx` — integrate `StarterPrompts`
- `chat/components/ArtifactPanel.tsx` — refactored into `chat/preview/FileTreePreview.tsx` (same logic, new location)
- `skills/creator/*` — migrate to shared components (Phase 2 late)

**Deleted (~4 files)**:
- `chat/components/ArtifactsDrawer.tsx`
- `chat/components/CompactArtifactStatus.tsx`
- `chat/components/ToolExecutionPanel.tsx` — merged into PreviewPanel
- `chat/components/CompactToolStatus.tsx` — replaced by ToolCallBadge

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Phase 1 regressions | Run full E2E after each extraction step: send message, streaming, switch conversation, tool/file viewing |
| Preview panel squeezes conversation on small screens | Set `minSize` breakpoint; width < 768px falls back to overlay mode |
| Shared component over-generalization | First version only extracts Chat + Skill Creator common parts, no premature abstraction |
| useReducer migration misses state | 1:1 mapping of all 14 existing useState; TypeScript strict types catch omissions |
| Skill Creator migration breaks existing flow | Phase 2 Step 5 is last; by then shared components are battle-tested in Chat |
| Context re-renders on streaming deltas | Split into `ChatStateContext` (low-frequency) and `ChatStreamContext` (high-frequency); components subscribe only to what they need |
| Two reducer scopes conflict (`useChatSession` + `useChatReducer`) | Clear boundary: `useChatSession` owns pre-conversation form state only, `useChatReducer` owns active conversation. `ChatHome.onStartChat()` is the handoff point |
| Import path breakage from file moves | Use barrel exports (`index.ts`) in new directories; update imports in one pass with IDE refactoring tools |
| Overlay-to-grid layout migration complexity | Phase 1 Step 6 wraps existing overlays as-is; the actual layout switch happens in Phase 2 Step 2, isolated from other changes |

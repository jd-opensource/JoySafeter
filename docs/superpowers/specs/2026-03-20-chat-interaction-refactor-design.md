# Chat Interaction Refactor Design

Date: 2026-03-20
Status: Draft

## Problem Statement

The current Chat implementation has a significantly inferior interaction experience compared to the Skill Creator. Key gaps:

1. **No guided entry** — users face a blank input box after selecting a mode
2. **Opaque tool calls** — raw tool names (`execute_code`, `write_file`) shown as badges, unintelligible to users
3. **Passive artifact viewing** — Artifacts Drawer requires manual click to open, not proactive
4. **No per-message actions** — only global Send/Stop, no Copy/Retry/Continue on individual messages
5. **Monolithic architecture** — `ChatInterface.tsx` is 700+ lines with 12+ `useState` calls, mixing layout, logic, and state

## Goals

- Bring Skill Creator's proven interaction patterns into Chat while preserving free-form conversation
- Establish a shared component library so both Chat and Skill Creator maintain consistent UX
- Refactor Chat architecture to support future interaction enhancements
- Execute in two phases: architecture cleanup first, then interaction enhancement

## Non-Goals

- Converting Chat into a wizard/step-by-step flow
- Building a plugin system for arbitrary mode customization
- Rewriting the backend streaming protocol

---

## Architecture Overview

### Target Structure

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

shared/
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

Replace 12+ `useState` with a single `useReducer` + Context:

```typescript
interface ChatState {
  messages: Message[]
  threadId: string | null
  streaming: {
    isProcessing: boolean
    isSubmitting: boolean
    text: string
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
  }
  mode: {
    currentMode: string | undefined
    currentGraphId: string | null
  }
}

type ChatAction =
  | { type: 'SET_THREAD'; threadId: string }
  | { type: 'APPEND_MESSAGE'; message: Message }
  | { type: 'UPDATE_MESSAGE'; id: string; patch: Partial<Message> }
  | { type: 'SET_MESSAGES'; messages: Message[] }
  | { type: 'STREAM_START' }
  | { type: 'STREAM_CONTENT'; delta: string }
  | { type: 'STREAM_DONE' }
  | { type: 'FILE_EVENT'; path: string; info: FileInfo }
  | { type: 'TOOL_START'; tool: ToolCall }
  | { type: 'TOOL_END'; id: string; result: string }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'TOGGLE_PREVIEW' }
  | { type: 'SET_MODE'; mode: string; graphId: string | null }
  | { type: 'RESET' }
```

Child components consume state via Context instead of prop drilling.

---

## Shared Component Library

### 1. ToolCallDisplay — Human-Readable Tool Calls

**Registry pattern** for extensible tool name mapping:

```typescript
interface ToolDisplayConfig {
  label: string
  icon?: React.ReactNode
  formatArgs?: (args: any) => string
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

Click fills the input (does not auto-submit), allowing user modification before sending.

---

## Layout Refactoring

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

```typescript
const defaultRules: TriggerRule[] = [
  { event: 'file_event',  action: 'show',  tab: 'files' },
  { event: 'tool_click',  action: 'show',  tab: 'tool' },
  { event: 'stream_done', action: 'hide',
    condition: (state) => Object.keys(state.fileTree).length === 0 },
]
```

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

**Completion criteria**: `ChatInterface.tsx` reduced to < 50 lines (Provider + Layout glue). All existing functionality unchanged.

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
- `chat/ChatInterface.tsx` — drastically simplified to glue layer
- `chat/components/MessageItem.tsx` → `MessageBubble`, integrates new components
- `chat/components/ThreadContent.tsx` → `MessageList`, simplified
- `chat/hooks/useBackendChatStream.ts` — adapted to dispatch
- `chat/config/modeConfig.ts` — add `starterPrompts` field
- `chat/components/ChatHome.tsx` — integrate `StarterPrompts`
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
| useReducer migration misses state | 1:1 mapping of all existing useState; TypeScript strict types catch omissions |
| Skill Creator migration breaks existing flow | Phase 2 Step 5 is last; by then shared components are battle-tested in Chat |

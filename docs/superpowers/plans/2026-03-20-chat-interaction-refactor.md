# Chat Interaction Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Chat to borrow Skill Creator's proven UX patterns (human-readable tool calls, persistent preview panel, per-message actions, starter prompts) while preserving free-form conversation.

**Architecture:** Two-phase approach. Phase 1 extracts ChatInterface's 14 useState into a useReducer + Context, splits the 683-line component into focused modules (ChatLayout, ConversationPanel, PreviewPanel, ChatProvider). Phase 2 introduces shared components (ToolCallDisplay, ActionBar, StarterPrompts) and converts the overlay-based side panels into a ResizablePanel column.

**Tech Stack:** React 18, Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui ResizablePanel, TanStack Query

**Spec:** `docs/superpowers/specs/2026-03-20-chat-interaction-refactor-design.md`

---

## File Structure

All paths relative to `frontend/app/`.

**Phase 1 — New files:**
| File | Responsibility |
|------|---------------|
| `chat/hooks/useChatReducer.ts` | ChatState/ChatAction types, reducer function, initial state |
| `chat/ChatProvider.tsx` | ChatStateContext + ChatStreamContext providers |
| `chat/ChatLayout.tsx` | Three-column ResizablePanelGroup skeleton |
| `chat/conversation/ConversationPanel.tsx` | Message list + streaming + input container |
| `chat/conversation/MessageList.tsx` | Message rendering (from ThreadContent) |
| `chat/conversation/MessageBubble.tsx` | Single message (from MessageItem) |
| `chat/conversation/ChatInput.tsx` | Input (moved from components/) |
| `chat/conversation/index.ts` | Barrel export |
| `chat/preview/PreviewPanel.tsx` | Tab-based preview container |
| `chat/preview/FileTreePreview.tsx` | File tree + code viewer (from ArtifactPanel) |
| `chat/preview/index.ts` | Barrel export |
| `chat/hooks/usePreviewTrigger.ts` | Auto-expand/collapse logic |
| `chat/types.ts` | Extended with FileTreeEntry, NodeLogEntry, MessageMetadata |

**Phase 1 — Modified files:**
| File | Change |
|------|--------|
| `chat/ChatInterface.tsx` | Rename to ChatPage.tsx, reduce to <50 lines |
| `chat/page.tsx` | Update import from ChatInterface to ChatPage |
| `chat/hooks/useBackendChatStream.ts` | Accept dispatch instead of setMessages |

**Phase 1 — Deleted files (Phase 2 Step 2):**
| File | Replaced by |
|------|------------|
| `chat/components/ArtifactsDrawer.tsx` | preview/PreviewPanel |
| `chat/components/CompactArtifactStatus.tsx` | PreviewPanel auto-expand |
| `chat/components/ToolExecutionPanel.tsx` | preview/PreviewPanel tool tab |
| `chat/components/CompactToolStatus.tsx` | shared/ToolCallDisplay |

**Phase 2 — New files:**
| File | Responsibility |
|------|---------------|
| `shared/ToolCallDisplay/toolDisplayRegistry.ts` | Tool name → label registry |
| `shared/ToolCallDisplay/ToolCallBadge.tsx` | Compact inline tool display |
| `shared/ToolCallDisplay/ToolCallDetail.tsx` | Expanded tool detail view |
| `shared/ToolCallDisplay/index.ts` | Barrel export |
| `shared/ActionBar/ActionBar.tsx` | Per-message action container |
| `shared/ActionBar/actions/CopyAction.tsx` | Copy message content |
| `shared/ActionBar/actions/RetryAction.tsx` | Retry message |
| `shared/ActionBar/index.ts` | Barrel export |
| `shared/StarterPrompts/StarterPrompts.tsx` | Guided start chips |
| `shared/StarterPrompts/index.ts` | Barrel export |

---

## Phase 1: Architecture Cleanup

### Task 1: Extend types.ts with typed metadata

**Files:**
- Modify: `chat/types.ts` (71 lines)

- [ ] **Step 1: Add FileTreeEntry, NodeLogEntry, MessageMetadata types**

Add above the existing `Message` interface at line 25:

```typescript
export interface FileTreeEntry {
  action: string
  size?: number
  timestamp?: number
}

export interface NodeLogEntry {
  type: 'command' | 'route_decision' | 'loop_iteration' | 'parallel_task' | 'state_update' | 'node_transition'
  nodeName: string
  timestamp: number
  data?: Record<string, unknown>
}

export interface MessageMetadata {
  fileTree?: Record<string, FileTreeEntry>
  nodeExecutionLog?: NodeLogEntry[]
  currentNode?: string
  lastNode?: string
  lastRunId?: string
  lastUpdate?: number
  lastRouteDecision?: any
  lastLoopIteration?: any
  [key: string]: any  // keep backwards compat
}
```

Update the `Message` interface to use `MessageMetadata`:

```typescript
export interface Message {
  // ... existing fields unchanged
  metadata?: MessageMetadata
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No new errors (existing errors may remain)

- [ ] **Step 3: Commit**

```bash
git add frontend/app/chat/types.ts
git commit -m "refactor(chat): add typed FileTreeEntry, NodeLogEntry, MessageMetadata to types.ts"
```

---

### Task 2: Create useChatReducer and ChatProvider

**Files:**
- Create: `chat/hooks/useChatReducer.ts`
- Create: `chat/ChatProvider.tsx`

- [ ] **Step 1: Create useChatReducer.ts**

```typescript
'use client'

import { useReducer } from 'react'
import type { Message, ToolCall, FileTreeEntry, NodeLogEntry } from '../types'

// ─── State ───────────────────────────────────────────────────────────────────
export interface ChatState {
  messages: Message[]
  threadId: string | null
  input: string
  streaming: {
    isProcessing: boolean
    isSubmitting: boolean
    text: string
    nodeExecutionLog: NodeLogEntry[]
  }
  preview: {
    visible: boolean
    fileTree: Record<string, FileTreeEntry>
    activeFile: string | null
    userDismissed: boolean
  }
  ui: {
    sidebarVisible: boolean
    selectedTool: ToolCall | null
    showNoDefaultModelNotice: boolean
  }
  mode: {
    currentMode: string | undefined
    currentGraphId: string | null
    hasShownApkPrompt: boolean
  }
}

export const initialChatState: ChatState = {
  messages: [],
  threadId: null,
  input: '',
  streaming: {
    isProcessing: false,
    isSubmitting: false,
    text: '',
    nodeExecutionLog: [],
  },
  preview: {
    visible: false,
    fileTree: {},
    activeFile: null,
    userDismissed: false,
  },
  ui: {
    sidebarVisible: false,
    selectedTool: null,
    showNoDefaultModelNotice: false,
  },
  mode: {
    currentMode: undefined,
    currentGraphId: null,
    hasShownApkPrompt: false,
  },
}

// ─── Actions ─────────────────────────────────────────────────────────────────
export type ChatAction =
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
  | { type: 'FILE_EVENT'; path: string; info: FileTreeEntry }
  | { type: 'TOOL_START'; tool: ToolCall }
  | { type: 'TOOL_END'; id: string; result: string }
  // Node execution (agent mode)
  | { type: 'NODE_START'; nodeId: string; label: string }
  | { type: 'NODE_END'; nodeId: string }
  | { type: 'NODE_LOG'; entry: NodeLogEntry }
  // UI
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'SHOW_PREVIEW'; tab?: string }
  | { type: 'HIDE_PREVIEW' }
  | { type: 'SELECT_TOOL'; tool: ToolCall | null }
  | { type: 'DISMISS_MODEL_NOTICE' }
  | { type: 'SHOW_MODEL_NOTICE' }
  // Mode
  | { type: 'SET_MODE'; mode: string; graphId: string | null }
  | { type: 'SET_APK_PROMPT_SHOWN' }

// ─── Reducer ─────────────────────────────────────────────────────────────────
export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'SET_THREAD':
      return { ...state, threadId: action.threadId }

    case 'RESET':
      return {
        ...initialChatState,
        ui: { ...initialChatState.ui, sidebarVisible: state.ui.sidebarVisible },
      }

    case 'APPEND_MESSAGE':
      return { ...state, messages: [...state.messages, action.message] }

    case 'UPDATE_MESSAGE':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, ...action.patch } : m
        ),
      }

    case 'SET_MESSAGES':
      return { ...state, messages: action.messages }

    case 'SET_INPUT':
      return { ...state, input: action.value }

    case 'STREAM_START':
      return {
        ...state,
        streaming: {
          ...state.streaming,
          isProcessing: true,
          isSubmitting: false,
          text: '',
          nodeExecutionLog: [],
        },
        preview: { ...state.preview, userDismissed: false },
      }

    case 'STREAM_CONTENT': {
      const lastMsg = state.messages[state.messages.length - 1]
      if (!lastMsg || lastMsg.role !== 'assistant') return state
      return {
        ...state,
        streaming: { ...state.streaming, text: (lastMsg.content ?? '') + action.delta },
      }
    }

    case 'STREAM_DONE':
      return {
        ...state,
        streaming: { ...state.streaming, isProcessing: false, isSubmitting: false, text: '' },
      }

    case 'STREAM_ERROR':
      return {
        ...state,
        streaming: { ...state.streaming, isProcessing: false, isSubmitting: false },
      }

    case 'FILE_EVENT':
      return {
        ...state,
        preview: {
          ...state.preview,
          fileTree: { ...state.preview.fileTree, [action.path]: action.info },
        },
      }

    case 'TOOL_START':
      return {
        ...state,
        messages: state.messages.map((m, i) =>
          i === state.messages.length - 1
            ? { ...m, tool_calls: [...(m.tool_calls ?? []), action.tool] }
            : m
        ),
      }

    case 'TOOL_END':
      return {
        ...state,
        messages: state.messages.map((m, i) =>
          i === state.messages.length - 1
            ? {
                ...m,
                tool_calls: m.tool_calls?.map((tc) =>
                  tc.id === action.id ? { ...tc, status: 'completed' as const, result: action.result, endTime: Date.now() } : tc
                ),
              }
            : m
        ),
      }

    case 'NODE_START':
      return {
        ...state,
        messages: state.messages.map((m, i) =>
          i === state.messages.length - 1
            ? { ...m, metadata: { ...m.metadata, currentNode: action.label } }
            : m
        ),
      }

    case 'NODE_END':
      return state // currentNode cleared on next NODE_START or STREAM_DONE

    case 'NODE_LOG':
      return {
        ...state,
        streaming: {
          ...state.streaming,
          nodeExecutionLog: [...state.streaming.nodeExecutionLog, action.entry],
        },
      }

    case 'TOGGLE_SIDEBAR':
      return { ...state, ui: { ...state.ui, sidebarVisible: !state.ui.sidebarVisible } }

    case 'SHOW_PREVIEW':
      return { ...state, preview: { ...state.preview, visible: true } }

    case 'HIDE_PREVIEW':
      return { ...state, preview: { ...state.preview, visible: false, userDismissed: true } }

    case 'SELECT_TOOL':
      return { ...state, ui: { ...state.ui, selectedTool: action.tool } }

    case 'DISMISS_MODEL_NOTICE':
      return { ...state, ui: { ...state.ui, showNoDefaultModelNotice: false } }

    case 'SHOW_MODEL_NOTICE':
      return { ...state, ui: { ...state.ui, showNoDefaultModelNotice: true } }

    case 'SET_MODE':
      return {
        ...state,
        mode: { ...state.mode, currentMode: action.mode, currentGraphId: action.graphId },
      }

    case 'SET_APK_PROMPT_SHOWN':
      return { ...state, mode: { ...state.mode, hasShownApkPrompt: true } }

    default:
      return state
  }
}

export function useChatReducer(initialState?: Partial<ChatState>) {
  return useReducer(chatReducer, { ...initialChatState, ...initialState })
}
```

- [ ] **Step 2: Create ChatProvider.tsx**

```typescript
'use client'

import React, { createContext, useContext, useMemo } from 'react'
import type { ChatState, ChatAction } from './hooks/useChatReducer'
import { useChatReducer, initialChatState } from './hooks/useChatReducer'

// Low-frequency context: messages, UI, mode
interface ChatStateContextValue {
  state: ChatState
  dispatch: React.Dispatch<ChatAction>
}

// High-frequency context: streaming text, isProcessing
interface ChatStreamContextValue {
  text: string
  isProcessing: boolean
  isSubmitting: boolean
}

const ChatStateContext = createContext<ChatStateContextValue | null>(null)
const ChatStreamContext = createContext<ChatStreamContextValue | null>(null)

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useChatReducer()

  const stateValue = useMemo(
    () => ({ state, dispatch }),
    // Exclude streaming fields from dependency to avoid re-rendering state consumers on every delta
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.messages, state.threadId, state.input, state.preview, state.ui, state.mode, dispatch]
  )

  const streamValue = useMemo(
    () => ({
      text: state.streaming.text,
      isProcessing: state.streaming.isProcessing,
      isSubmitting: state.streaming.isSubmitting,
    }),
    [state.streaming.text, state.streaming.isProcessing, state.streaming.isSubmitting]
  )

  return (
    <ChatStateContext.Provider value={stateValue}>
      <ChatStreamContext.Provider value={streamValue}>
        {children}
      </ChatStreamContext.Provider>
    </ChatStateContext.Provider>
  )
}

export function useChatState() {
  const ctx = useContext(ChatStateContext)
  if (!ctx) throw new Error('useChatState must be used within ChatProvider')
  return ctx
}

export function useChatStream() {
  const ctx = useContext(ChatStreamContext)
  if (!ctx) throw new Error('useChatStream must be used within ChatProvider')
  return ctx
}

export { ChatStateContext, ChatStreamContext }
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No new errors

- [ ] **Step 4: Commit**

```bash
git add frontend/app/chat/hooks/useChatReducer.ts frontend/app/chat/ChatProvider.tsx
git commit -m "refactor(chat): add useChatReducer and ChatProvider with dual-context split"
```

---

### Task 3: Adapt useBackendChatStream to dispatch

**Files:**
- Modify: `chat/hooks/useBackendChatStream.ts` (549 lines)

This is the most critical migration step. The hook must accept `dispatch` instead of `setMessages` and convert every SSE event handler from `safeSetMessages(prev => ...)` to `dispatch({ type: ... })`.

- [ ] **Step 1: Change hook signature**

Replace the function signature (line 26):

```typescript
// Before:
export const useBackendChatStream = (
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
)

// After:
export const useBackendChatStream = (
  dispatch: React.Dispatch<ChatAction>,
)
```

Add import at top:
```typescript
import type { ChatAction } from './useChatReducer'
```

- [ ] **Step 2: Replace all safeSetMessages calls with dispatch calls**

Key transformations (referencing actual event handlers in the file):

| SSE Event | Current pattern | New pattern |
|-----------|----------------|-------------|
| Before stream (blank assistant msg) | `setMessages(prev => [...prev, blankMsg])` | `dispatch({ type: 'APPEND_MESSAGE', message: blankMsg })` |
| `content` | `safeSetMessages(prev => prev.map(...update last msg content))` | `dispatch({ type: 'UPDATE_MESSAGE', id: lastMsgId, patch: { content: accumulated } })` |
| `tool_start` | `safeSetMessages(prev => prev.map(...push tool to last msg))` | `dispatch({ type: 'TOOL_START', tool: { id, name, args, status: 'running', startTime } })` |
| `tool_end` | `safeSetMessages(prev => prev.map(...update tool status))` | `dispatch({ type: 'TOOL_END', id, result })` |
| `file_event` | `safeSetMessages(prev => prev.map(...update metadata.fileTree))` | `dispatch({ type: 'FILE_EVENT', path, info: { action, size, timestamp } })` |
| `node_start` | `safeSetMessages(prev => prev.map(...set metadata.currentNode))` | `dispatch({ type: 'NODE_START', nodeId, label })` |
| `node_end` | `safeSetMessages(prev => prev.map(...clear currentNode))` | `dispatch({ type: 'NODE_END', nodeId })` |
| `command`/`route_decision`/etc. | `nodeExecutionLog.push(...); safeSetMessages(...)` | `dispatch({ type: 'NODE_LOG', entry: { type, nodeName, timestamp, data } })` |
| `error` | `safeSetMessages(prev => prev.map(...append error))` | `dispatch({ type: 'STREAM_ERROR', error: text })` |
| `done` | `safeSetMessages(prev => prev.map(...set isStreaming false))` | `dispatch({ type: 'STREAM_DONE' })` |
| `thread_id` | `threadIdRef.current = id` | Keep ref + `dispatch({ type: 'SET_THREAD', threadId: id })` |

Remove the `nodeExecutionLog` closure variable — it is now in the reducer state.

Remove `safeSetMessages` wrapper — dispatch is already safe to call after unmount (no-op on unmounted reducer).

Keep `abortRef` and `isMountedRef` for abort logic.

- [ ] **Step 3: Update sendMessage to dispatch STREAM_START**

At the beginning of `sendMessage`, before creating the blank assistant message:
```typescript
dispatch({ type: 'STREAM_START' })
```

- [ ] **Step 4: Keep the lastMsgId tracking**

The hook needs to track the ID of the current assistant message being streamed. Use a ref:
```typescript
const currentMsgIdRef = useRef<string>('')
// Set when creating blank assistant message
currentMsgIdRef.current = blankMsg.id
// Use in UPDATE_MESSAGE dispatches
dispatch({ type: 'UPDATE_MESSAGE', id: currentMsgIdRef.current, patch: { ... } })
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: Errors in ChatInterface.tsx (expected — it still passes setMessages). No errors in useBackendChatStream.ts itself.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/chat/hooks/useBackendChatStream.ts
git commit -m "refactor(chat): adapt useBackendChatStream to dispatch-based state management"
```

---

### Task 4: Create ConversationPanel and move components

**Files:**
- Create: `chat/conversation/ConversationPanel.tsx`
- Create: `chat/conversation/MessageList.tsx` (copy from `chat/components/ThreadContent.tsx`)
- Create: `chat/conversation/MessageBubble.tsx` (copy from `chat/components/MessageItem.tsx`)
- Move: `chat/components/ChatInput.tsx` → `chat/conversation/ChatInput.tsx`
- Create: `chat/conversation/index.ts`

- [ ] **Step 1: Copy ThreadContent.tsx to MessageList.tsx**

Copy `chat/components/ThreadContent.tsx` to `chat/conversation/MessageList.tsx`. Update:
- Rename component from `ThreadContent` to `MessageList`
- Update import of `MessageItem` to `MessageBubble` from `./MessageBubble`
- The props interface stays the same for now (will consume Context in Task 6)

- [ ] **Step 2: Copy MessageItem.tsx to MessageBubble.tsx**

Copy `chat/components/MessageItem.tsx` to `chat/conversation/MessageBubble.tsx`. Update:
- Rename component from `MessageItem` to `MessageBubble`
- Rename `MessageItemProps` to `MessageBubbleProps`
- Update import paths for types (now `../../types` instead of `../types`)

- [ ] **Step 3: Move ChatInput.tsx**

Copy `chat/components/ChatInput.tsx` to `chat/conversation/ChatInput.tsx`. Update import paths:
- `../hooks/useFileUpload` → `../../hooks/useFileUpload` (or from hooks directory)
- `../services/modeHandlers/types` → `../../services/modeHandlers/types`

- [ ] **Step 4: Create ConversationPanel.tsx**

This component replaces the middle section of ChatInterface (lines 561-616). It consumes ChatStateContext:

```typescript
'use client'

import React, { useRef, useEffect, useMemo } from 'react'
import { useChatState, useChatStream } from '../ChatProvider'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import type { ToolCall } from '../types'

interface ConversationPanelProps {
  onSubmit: (text: string, mode?: string, graphId?: string | null, files?: any[]) => void
  onStop: () => void
  onToolClick: (toolCall: ToolCall) => void
}

export default function ConversationPanel({ onSubmit, onStop, onToolClick }: ConversationPanelProps) {
  const { state, dispatch } = useChatState()
  const stream = useChatStream()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      })
    })
    return () => cancelAnimationFrame(id)
  }, [state.messages, stream.isProcessing])

  const agentStatus = useMemo<'idle' | 'running' | 'connecting' | 'error'>(
    () => (stream.isProcessing || stream.isSubmitting ? 'running' : 'idle'),
    [stream.isProcessing, stream.isSubmitting],
  )

  const lastMsg = state.messages[state.messages.length - 1]
  const streamingText = useMemo(() => {
    if (!lastMsg || lastMsg.role !== 'assistant') return ''
    if (!stream.isProcessing && !lastMsg.isStreaming) return ''
    return lastMsg.content ?? ''
  }, [lastMsg, stream.isProcessing])

  const currentNodeLabel = useMemo(
    () => lastMsg?.role === 'assistant' ? (lastMsg.metadata?.currentNode ?? undefined) : undefined,
    [lastMsg],
  )

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-hidden">
          <MessageList
            messages={state.messages}
            streamingText={streamingText}
            agentStatus={agentStatus}
            currentNodeLabel={currentNodeLabel}
            onToolClick={onToolClick}
            scrollContainerRef={scrollRef}
          />
        </div>
      </div>
      <div className="relative flex-shrink-0 bg-gray-50 px-6 pb-6 pt-2">
        <ChatInput
          input={state.input}
          setInput={(v) => dispatch({ type: 'SET_INPUT', value: v })}
          onSubmit={onSubmit}
          isProcessing={stream.isProcessing}
          onStop={onStop}
          currentMode={state.mode.currentMode}
          currentGraphId={state.mode.currentGraphId}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create barrel export**

```typescript
// chat/conversation/index.ts
export { default as ConversationPanel } from './ConversationPanel'
export { default as MessageList } from './MessageList'
export { default as MessageBubble } from './MessageBubble'
export { default as ChatInput } from './ChatInput'
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

- [ ] **Step 7: Commit**

```bash
git add frontend/app/chat/conversation/
git commit -m "refactor(chat): create conversation/ module with ConversationPanel, MessageList, MessageBubble"
```

---

### Task 5: Create PreviewPanel and FileTreePreview

**Files:**
- Create: `chat/preview/PreviewPanel.tsx`
- Create: `chat/preview/FileTreePreview.tsx` (from ArtifactPanel)
- Create: `chat/preview/index.ts`
- Create: `chat/hooks/usePreviewTrigger.ts`

- [ ] **Step 1: Copy ArtifactPanel.tsx to FileTreePreview.tsx**

Copy `chat/components/ArtifactPanel.tsx` (198 lines) to `chat/preview/FileTreePreview.tsx`. Update:
- Rename component from `ArtifactPanel` to `FileTreePreview`
- Update import paths

- [ ] **Step 2: Create PreviewPanel.tsx**

Tab-based container wrapping FileTreePreview and tool detail:

```typescript
'use client'

import React, { useState } from 'react'
import { X, FolderTree, Wrench } from 'lucide-react'
import { useChatState } from '../ChatProvider'
import FileTreePreview from './FileTreePreview'
import type { ToolCall } from '../types'

export default function PreviewPanel() {
  const { state, dispatch } = useChatState()
  const { preview, ui, threadId } = state
  const [activeTab, setActiveTab] = useState<'files' | 'tool'>('files')

  const hasFiles = Object.keys(preview.fileTree).length > 0
  const hasTool = !!ui.selectedTool

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header with tabs */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex gap-1">
          {hasFiles && (
            <button
              onClick={() => setActiveTab('files')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm ${
                activeTab === 'files' ? 'bg-gray-100 font-medium' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <FolderTree size={14} />
              Files ({Object.keys(preview.fileTree).length})
            </button>
          )}
          {hasTool && (
            <button
              onClick={() => setActiveTab('tool')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm ${
                activeTab === 'tool' ? 'bg-gray-100 font-medium' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Wrench size={14} />
              {ui.selectedTool?.name}
            </button>
          )}
        </div>
        <button
          onClick={() => dispatch({ type: 'HIDE_PREVIEW' })}
          className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'files' && threadId && (
          <FileTreePreview threadId={threadId} fileTree={preview.fileTree} />
        )}
        {activeTab === 'tool' && ui.selectedTool && (
          <div className="p-4">
            {/* Inline tool detail — simplified from ToolExecutionPanel for now */}
            <pre className="text-sm whitespace-pre-wrap">{JSON.stringify(ui.selectedTool, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create usePreviewTrigger.ts**

```typescript
'use client'

import { useEffect, useRef } from 'react'
import type { ChatState, ChatAction } from './useChatReducer'

export function usePreviewTrigger(
  state: ChatState,
  dispatch: React.Dispatch<ChatAction>,
) {
  const prevFileCountRef = useRef(0)

  useEffect(() => {
    const currentFileCount = Object.keys(state.preview.fileTree).length
    const isNew = currentFileCount > prevFileCountRef.current

    // Auto-show when new files appear (unless user dismissed)
    if (isNew && currentFileCount > 0 && !state.preview.visible && !state.preview.userDismissed) {
      dispatch({ type: 'SHOW_PREVIEW', tab: 'files' })
    }

    prevFileCountRef.current = currentFileCount
  }, [state.preview.fileTree, state.preview.visible, state.preview.userDismissed, dispatch])

  // Auto-hide when stream ends with no files
  useEffect(() => {
    if (
      !state.streaming.isProcessing &&
      Object.keys(state.preview.fileTree).length === 0 &&
      state.preview.visible
    ) {
      dispatch({ type: 'HIDE_PREVIEW' })
    }
  }, [state.streaming.isProcessing, state.preview.fileTree, state.preview.visible, dispatch])
}
```

- [ ] **Step 4: Create barrel export**

```typescript
// chat/preview/index.ts
export { default as PreviewPanel } from './PreviewPanel'
export { default as FileTreePreview } from './FileTreePreview'
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`

- [ ] **Step 6: Commit**

```bash
git add frontend/app/chat/preview/ frontend/app/chat/hooks/usePreviewTrigger.ts
git commit -m "refactor(chat): create preview/ module with PreviewPanel, FileTreePreview, usePreviewTrigger"
```

---

### Task 6: Create ChatLayout and wire everything together

**Files:**
- Create: `chat/ChatLayout.tsx`
- Modify: `chat/ChatInterface.tsx` → rename to `chat/ChatPage.tsx`
- Modify: `chat/page.tsx`

- [ ] **Step 1: Create ChatLayout.tsx**

```typescript
'use client'

import React, { useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { useDeployedGraphs, useWorkspaces } from '@/hooks/queries'
import { useAvailableModels } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'
import { conversationService } from '@/services/conversationService'

import ChatSidebar from './components/ChatSidebar'
import ChatHome from './components/ChatHome'
import { ConversationPanel } from './conversation'
import { PreviewPanel } from './preview'
import { useChatState, useChatStream } from './ChatProvider'
import { useBackendChatStream } from './hooks/useBackendChatStream'
import { usePreviewTrigger } from './hooks/usePreviewTrigger'
import { graphResolutionService } from './services/graphResolutionService'
import { generateId, Message } from './types'
import type { ToolCall } from './types'
// Import model notice dialog (extracted from old ChatInterface)
import { ModelNoticeDialog } from './components/ModelNoticeDialog'

export default function ChatLayout({ chatId: propChatId }: { chatId?: string | null }) {
  const { state, dispatch } = useChatState()
  const stream = useChatStream()
  const { t } = useTranslation()
  const router = useRouter()

  // Data fetching
  const { data: deployedAgents = [] } = useDeployedGraphs()
  const { data: workspacesData } = useWorkspaces()
  const personalWorkspaceId = workspacesData?.find((w) => w.type === 'personal')?.id ?? null
  const { data: availableModels = [], isSuccess: modelsLoaded, isError: modelsError } = useAvailableModels('chat', { enabled: true })

  // Hook integrations
  const { sendMessage, stopMessage } = useBackendChatStream(dispatch)
  usePreviewTrigger(state, dispatch)

  // Keyboard shortcut: Cmd+B toggle sidebar
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

  // Model notice check
  // ... (migrate useEffect from ChatInterface lines 86-103)

  // Sync propChatId
  // ... (migrate useEffect from ChatInterface lines 172-190)

  // handleSubmit, handleSelectConversation, handleNewChat, handleToolClick
  // ... (migrate from ChatInterface lines 244-430, using dispatch instead of setState)

  const hasMessages = state.messages.length > 0 || !!state.threadId || !!propChatId

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-gray-50">
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Sidebar */}
        {state.ui.sidebarVisible && (
          <>
            <ResizablePanel defaultSize={12} minSize={10} maxSize={25}>
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

        {/* Conversation */}
        <ResizablePanel defaultSize={state.preview.visible ? 55 : 88} minSize={40}>
          {!hasMessages ? (
            <ChatHome
              onStartChat={handleSubmit}
              onSelectConversation={handleSelectConversation}
              isProcessing={stream.isProcessing}
              onStop={() => stopMessage(state.threadId)}
            />
          ) : (
            <ConversationPanel
              onSubmit={handleSubmit}
              onStop={() => stopMessage(state.threadId)}
              onToolClick={handleToolClick}
            />
          )}
        </ResizablePanel>

        {/* Preview */}
        {state.preview.visible && (
          <>
            <ResizableHandle className="w-px bg-gray-200" />
            <ResizablePanel defaultSize={45} minSize={30} maxSize={60}>
              <PreviewPanel />
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>

      <ModelNoticeDialog />
    </div>
  )
}
```

Note: The `handleSubmit`, `handleSelectConversation`, `handleNewChat`, `handleToolClick` callbacks are migrated directly from ChatInterface lines 244-430, replacing all `setXxx()` calls with `dispatch({ type: 'XXX', ... })`.

- [ ] **Step 2: Rename ChatInterface.tsx to ChatPage.tsx**

Replace entire content with:

```typescript
'use client'

import { ChatProvider } from './ChatProvider'
import ChatLayout from './ChatLayout'

interface ChatPageProps {
  chatId?: string | null
}

export default function ChatPage({ chatId }: ChatPageProps) {
  return (
    <ChatProvider>
      <ChatLayout chatId={chatId} />
    </ChatProvider>
  )
}
```

- [ ] **Step 3: Update page.tsx import**

In `chat/page.tsx` (line 5), change:
```typescript
// Before:
import ChatInterface from './ChatInterface'
// After:
import ChatPage from './ChatPage'
```

And update the JSX (line 15):
```typescript
// Before:
<ChatInterface chatId={threadId} />
// After:
<ChatPage chatId={threadId} />
```

- [ ] **Step 4: Extract ModelNoticeDialog**

Create `chat/components/ModelNoticeDialog.tsx` containing the AlertDialog from ChatInterface lines 648-679. This component consumes ChatStateContext for `showNoDefaultModelNotice` and dispatches `DISMISS_MODEL_NOTICE`.

- [ ] **Step 5: Verify app compiles and runs**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Run: `cd frontend && npm run dev` — verify chat page loads, can send messages, sidebar works, conversation switching works.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/chat/ChatLayout.tsx frontend/app/chat/ChatPage.tsx frontend/app/chat/page.tsx frontend/app/chat/components/ModelNoticeDialog.tsx
git rm frontend/app/chat/ChatInterface.tsx
git commit -m "refactor(chat): replace ChatInterface with ChatProvider + ChatLayout + ChatPage (<50 lines)"
```

---

## Phase 2: Interaction Enhancement

### Task 7: Shared ToolCallDisplay components

**Files:**
- Create: `shared/ToolCallDisplay/toolDisplayRegistry.ts`
- Create: `shared/ToolCallDisplay/ToolCallBadge.tsx`
- Create: `shared/ToolCallDisplay/ToolCallDetail.tsx`
- Create: `shared/ToolCallDisplay/index.ts`

- [ ] **Step 1: Create toolDisplayRegistry.ts**

Migrate and generalize from `skills/creator/components/toolDisplayUtils.ts` (140 lines). Include all tool name mappings from that file plus the icon logic from `MessageItem.tsx`'s `ToolCallItem`.

```typescript
export interface ToolDisplayConfig {
  label: string
  icon?: string  // lucide icon name
  formatArgs?: (args: Record<string, any>) => string
  formatDetail?: (args: Record<string, any>) => string
  category: 'file' | 'code' | 'search' | 'network' | 'other'
}

const registry = new Map<string, ToolDisplayConfig>()

// Register all known tools (from toolDisplayUtils.ts)
function registerDefaults() {
  register('read_file',     { label: 'Reading',        category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('read',          { label: 'Reading',        category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('write_file',    { label: 'Writing',        category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('write',         { label: 'Writing',        category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('create_file',   { label: 'Creating',       category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('edit_file',     { label: 'Editing',        category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('edit',          { label: 'Editing',        category: 'file',   formatArgs: a => shortenPath(a.path || a.file_path) })
  register('str_replace_editor', { label: 'Editing',   category: 'file',   formatArgs: a => shortenPath(a.path) })
  register('execute',       { label: 'Executing',      category: 'code',   formatArgs: a => truncate(a.command, 60) })
  register('bash',          { label: 'Running',        category: 'code',   formatArgs: a => truncate(a.command, 60) })
  register('run_command',   { label: 'Running',        category: 'code',   formatArgs: a => truncate(a.command, 60) })
  register('python',        { label: 'Python',         category: 'code',   formatArgs: a => truncate(a.code?.split('\n')[0], 60) })
  register('python_interpreter', { label: 'Python',    category: 'code' })
  register('web_search',    { label: 'Searching',      category: 'search', formatArgs: a => a.query })
  register('preview_skill', { label: 'Deploying skill', category: 'other', formatArgs: a => a.skill_name })
  register('glob',          { label: 'Finding files',  category: 'search' })
  register('find_files',    { label: 'Finding files',  category: 'search' })
  register('grep',          { label: 'Searching code', category: 'search' })
  register('search',        { label: 'Searching',      category: 'search' })
  register('ls',            { label: 'Listing',        category: 'file',   formatArgs: a => shortenPath(a.path) })
  register('list_directory', { label: 'Listing',       category: 'file',   formatArgs: a => shortenPath(a.path) })
  register('think',         { label: 'Thinking...',    category: 'other' })
  register('reasoning',     { label: 'Thinking...',    category: 'other' })
  register('write_todos',   { label: 'Updating plan',  category: 'other' })
  register('todo_write',    { label: 'Updating plan',  category: 'other' })
  register('planner',       { label: 'Planning',       category: 'other' })
}

export function register(name: string, config: ToolDisplayConfig) { registry.set(name, config) }
export function getToolDisplay(name: string, args: Record<string, any>): { label: string; detail: string; category: string } { /* ... */ }

function shortenPath(p?: string): string { /* from toolDisplayUtils.ts */ }
function truncate(s?: string, max = 60): string { /* ... */ }

registerDefaults()
```

- [ ] **Step 2: Create ToolCallBadge.tsx**

Compact inline badge showing icon + label + args summary + status indicator. Replaces `ToolCallItem` inside `MessageItem.tsx`.

- [ ] **Step 3: Create ToolCallDetail.tsx**

Generalized from `ToolExecutionPanel.tsx` (375 lines) — shows tool input JSON, output (JSON/Markdown/text), copy buttons, timestamp.

- [ ] **Step 4: Create barrel export**

- [ ] **Step 5: Integrate into MessageBubble.tsx**

Replace the inline `ToolCallItem` in `MessageBubble.tsx` with `ToolCallBadge` from the shared library.

- [ ] **Step 6: Verify TypeScript compiles and tool display renders correctly**

- [ ] **Step 7: Commit**

```bash
git add frontend/app/shared/ToolCallDisplay/
git commit -m "feat(chat): add shared ToolCallDisplay with human-readable tool labels and badge"
```

---

### Task 8: Persistent preview panel (layout switch)

**Files:**
- Modify: `chat/ChatLayout.tsx` (already has ResizablePanel structure from Task 6)
- Delete: `chat/components/ArtifactsDrawer.tsx`
- Delete: `chat/components/CompactArtifactStatus.tsx`
- Delete: `chat/components/ToolExecutionPanel.tsx`
- Delete: `chat/components/CompactToolStatus.tsx`
- Modify: `chat/conversation/ChatInput.tsx` — remove `compactToolStatus` and `compactArtifactStatus` props

- [ ] **Step 1: Remove overlay rendering from ChatLayout**

Remove the `renderFloatingPanel` pattern and the `SIDE_PANEL_WIDTH` / `CONTENT_PR` / `CONTENT_MR` constants. The ResizablePanel preview column replaces them.

- [ ] **Step 2: Remove compact status slot props from ChatInput**

Remove `compactToolStatus` and `compactArtifactStatus` props from `ChatInput.tsx` — the preview panel is now always visible when content exists, no compact trigger needed.

- [ ] **Step 3: Delete old overlay components**

```bash
git rm frontend/app/chat/components/ArtifactsDrawer.tsx
git rm frontend/app/chat/components/CompactArtifactStatus.tsx
git rm frontend/app/chat/components/ToolExecutionPanel.tsx
git rm frontend/app/chat/components/CompactToolStatus.tsx
```

- [ ] **Step 4: Add responsive fallback**

In `ChatLayout.tsx`, add a media query check. For `window.innerWidth < 768`, render PreviewPanel as a slide-over overlay instead of a ResizablePanel column.

- [ ] **Step 5: Verify app works end-to-end**

Manual test: send a message that triggers file creation, verify preview panel auto-opens with file tree, close it manually, send another message and verify `userDismissed` suppresses auto-open, verify new conversation resets the flag.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(chat): replace overlay panels with persistent ResizablePanel preview column"
```

---

### Task 9: Per-message ActionBar

**Files:**
- Create: `shared/ActionBar/ActionBar.tsx`
- Create: `shared/ActionBar/actions/CopyAction.tsx`
- Create: `shared/ActionBar/actions/RetryAction.tsx`
- Create: `shared/ActionBar/index.ts`
- Modify: `chat/conversation/MessageBubble.tsx`

- [ ] **Step 1: Create ActionBar.tsx**

```typescript
interface ActionConfig {
  id: string
  label: string
  icon: React.ComponentType<{ size?: number }>
  onClick: () => void
  show?: boolean
}

interface ActionBarProps {
  actions: ActionConfig[]
  visible: boolean  // hover state or isLast
}
```

Renders a row of icon buttons. Fade in/out via `opacity` + `transition`.

- [ ] **Step 2: Create CopyAction and RetryAction**

`CopyAction`: copies message content to clipboard, shows checkmark for 2s.
`RetryAction`: calls `onRetry(messageId)` which re-sends the preceding user message.

- [ ] **Step 3: Integrate into MessageBubble**

Add `ActionBar` below assistant message content. Show on hover (via `group-hover` Tailwind class). Always show on the last assistant message.

- [ ] **Step 4: Create barrel export**

- [ ] **Step 5: Verify actions work**

- [ ] **Step 6: Commit**

```bash
git add frontend/app/shared/ActionBar/
git commit -m "feat(chat): add per-message ActionBar with Copy and Retry actions"
```

---

### Task 10: Starter prompts for guided entry

**Files:**
- Create: `shared/StarterPrompts/StarterPrompts.tsx`
- Create: `shared/StarterPrompts/index.ts`
- Modify: `chat/config/modeConfig.ts` — add `starterPrompts` field
- Modify: `chat/components/ChatHome.tsx` — integrate StarterPrompts

- [ ] **Step 1: Add starterPrompts to ModeConfig**

In `modeConfig.ts`, extend the interface:

```typescript
export interface StarterPrompt {
  labelKey: string
  promptKey: string
  icon: any
}

export interface ModeConfig {
  // ... existing fields
  starterPrompts?: StarterPrompt[]
}
```

Add prompts to `default-chat`:
```typescript
{
  id: 'default-chat',
  // ... existing
  starterPrompts: [
    { labelKey: 'chat.starter.analyzeCode', promptKey: 'chat.starter.analyzeCodePrompt', icon: Code },
    { labelKey: 'chat.starter.writeScript', promptKey: 'chat.starter.writeScriptPrompt', icon: Terminal },
    { labelKey: 'chat.starter.explainConcept', promptKey: 'chat.starter.explainConceptPrompt', icon: BookOpen },
  ]
}
```

- [ ] **Step 2: Create StarterPrompts.tsx**

```typescript
interface StarterPromptsProps {
  prompts: StarterPrompt[]
  onSelect: (prompt: string) => void
}
```

Renders a row of clickable chips. On click: calls `onSelect(t(prompt.promptKey))`, adds brief highlight animation.

- [ ] **Step 3: Integrate into ChatHome**

Below the mode cards in `ChatHome.tsx`, render `StarterPrompts` for the currently selected mode. On select, fill the input and focus the textarea.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/shared/StarterPrompts/ frontend/app/chat/config/modeConfig.ts frontend/app/chat/components/ChatHome.tsx
git commit -m "feat(chat): add starter prompts for guided entry experience"
```

---

### Task 11: Skill Creator migration to shared components

**Files:**
- Modify: `skills/creator/components/SkillCreatorChat.tsx`
- Modify: `skills/creator/components/toolDisplayUtils.ts` → deprecate, import from shared registry

- [ ] **Step 1: Replace toolDisplayUtils with shared registry**

In `SkillCreatorChat.tsx`, replace:
```typescript
import { formatToolDisplay } from './toolDisplayUtils'
```
with:
```typescript
import { getToolDisplay } from '@/app/shared/ToolCallDisplay'
```

Update all `formatToolDisplay()` calls to use `getToolDisplay()`.

- [ ] **Step 2: Replace inline tool badges with ToolCallBadge**

If the Skill Creator renders custom tool badges inline, replace them with `ToolCallBadge` from the shared library.

- [ ] **Step 3: Verify Skill Creator still works**

Manual test: navigate to `/skills/creator`, create a skill with AI, verify tool display is correct and preview works.

- [ ] **Step 4: Delete or deprecate toolDisplayUtils.ts**

Add a deprecation comment or delete if all imports are migrated.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/skills/creator/ frontend/app/shared/ToolCallDisplay/
git commit -m "refactor(skills): migrate Skill Creator to shared ToolCallDisplay components"
```

---

## Final Cleanup

### Task 12: Remove dead code and update imports

- [ ] **Step 1: Remove old ThreadContent and MessageItem**

If no other files import the old components:
```bash
git rm frontend/app/chat/components/ThreadContent.tsx
git rm frontend/app/chat/components/MessageItem.tsx
```

Keep `ChatSidebar.tsx` and `ChatHome.tsx` in `components/` — they are still used.

- [ ] **Step 2: Verify no broken imports**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -50`

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "refactor(chat): remove deprecated components and clean up imports"
```

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
    isSubmitting: boolean // optimistic "thinking" before SSE starts
    text: string
    nodeExecutionLog: NodeLogEntry[]
  }
  preview: {
    visible: boolean
    fileTree: Record<string, FileTreeEntry>
    activeFile: string | null
    userDismissed: boolean // set when user manually closes preview, resets on new stream
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
        // Preserve sidebar visibility across reset
        ui: { ...initialChatState.ui, sidebarVisible: state.ui.sidebarVisible },
      }

    case 'APPEND_MESSAGE':
      return { ...state, messages: [...state.messages, action.message] }

    case 'UPDATE_MESSAGE':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, ...action.patch } : m,
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
        streaming: {
          ...state.streaming,
          text: (lastMsg.content ?? '') + action.delta,
        },
      }
    }

    case 'STREAM_DONE':
      return {
        ...state,
        streaming: {
          ...state.streaming,
          isProcessing: false,
          isSubmitting: false,
          text: '',
        },
      }

    case 'STREAM_ERROR':
      return {
        ...state,
        streaming: {
          ...state.streaming,
          isProcessing: false,
          isSubmitting: false,
        },
      }

    case 'FILE_EVENT':
      return {
        ...state,
        preview: {
          ...state.preview,
          fileTree: {
            ...state.preview.fileTree,
            [action.path]: action.info,
          },
        },
      }

    case 'TOOL_START':
      return {
        ...state,
        messages: state.messages.map((m, i) =>
          i === state.messages.length - 1
            ? { ...m, tool_calls: [...(m.tool_calls ?? []), action.tool] }
            : m,
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
                  tc.id === action.id
                    ? { ...tc, status: 'completed' as const, result: action.result, endTime: Date.now() }
                    : tc,
                ),
              }
            : m,
        ),
      }

    case 'NODE_START':
      return {
        ...state,
        messages: state.messages.map((m, i) =>
          i === state.messages.length - 1
            ? { ...m, metadata: { ...m.metadata, currentNode: action.label } }
            : m,
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
      return {
        ...state,
        ui: { ...state.ui, sidebarVisible: !state.ui.sidebarVisible },
      }

    case 'SHOW_PREVIEW':
      return {
        ...state,
        preview: { ...state.preview, visible: true },
      }

    case 'HIDE_PREVIEW':
      return {
        ...state,
        preview: { ...state.preview, visible: false, userDismissed: true },
      }

    case 'SELECT_TOOL':
      return {
        ...state,
        ui: { ...state.ui, selectedTool: action.tool },
      }

    case 'DISMISS_MODEL_NOTICE':
      return {
        ...state,
        ui: { ...state.ui, showNoDefaultModelNotice: false },
      }

    case 'SHOW_MODEL_NOTICE':
      return {
        ...state,
        ui: { ...state.ui, showNoDefaultModelNotice: true },
      }

    case 'SET_MODE':
      return {
        ...state,
        mode: {
          ...state.mode,
          currentMode: action.mode,
          currentGraphId: action.graphId,
        },
      }

    case 'SET_APK_PROMPT_SHOWN':
      return {
        ...state,
        mode: { ...state.mode, hasShownApkPrompt: true },
      }

    default:
      return state
  }
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function useChatReducer(initialState?: Partial<ChatState>) {
  return useReducer(chatReducer, { ...initialChatState, ...initialState })
}

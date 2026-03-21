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
    messageId: string | null // id of the message being streamed
    metadata: Record<string, any> | null // latest metadata from content events
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
    messageId: null,
    metadata: null,
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
  | { type: 'STREAM_CONTENT'; delta: string; messageId: string; metadata?: Record<string, any> }
  | { type: 'STREAM_DONE'; messageId?: string }
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
  | { type: 'SET_SIDEBAR_VISIBLE'; visible: boolean }
  | { type: 'SHOW_PREVIEW' }
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
          messageId: null,
          metadata: null,
          nodeExecutionLog: [],
        },
        preview: { ...state.preview, userDismissed: false },
      }

    case 'STREAM_CONTENT': {
      // Only update streaming state — messages[] stays stable for ChatStateContext
      return {
        ...state,
        streaming: {
          ...state.streaming,
          text: state.streaming.text + action.delta,
          messageId: action.messageId,
          metadata: action.metadata || state.streaming.metadata,
        },
      }
    }

    case 'STREAM_DONE': {
      // Commit accumulated streaming text to the message
      const mid = action.messageId || state.streaming.messageId
      const hasContent = mid && state.streaming.text
      return {
        ...state,
        messages: hasContent
          ? state.messages.map((m) =>
              m.id === mid
                ? {
                    ...m,
                    content: state.streaming.text,
                    isStreaming: false,
                    metadata: state.streaming.metadata
                      ? { ...m.metadata, ...state.streaming.metadata }
                      : m.metadata,
                  }
                : m,
            )
          : state.messages,
        streaming: {
          ...state.streaming,
          isProcessing: false,
          isSubmitting: false,
          text: '',
          messageId: null,
          metadata: null,
        },
      }
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

    case 'SET_SIDEBAR_VISIBLE':
      if (state.ui.sidebarVisible === action.visible) return state
      return { ...state, ui: { ...state.ui, sidebarVisible: action.visible } }

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

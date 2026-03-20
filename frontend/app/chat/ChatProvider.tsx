'use client'

import React, { createContext, useContext, useMemo } from 'react'

import type { ChatState, ChatAction } from './hooks/useChatReducer'
import { useChatReducer } from './hooks/useChatReducer'

// ─── Low-frequency context: messages, UI, mode ──────────────────────────────

interface ChatStateContextValue {
  state: ChatState
  dispatch: React.Dispatch<ChatAction>
}

// ─── High-frequency context: streaming text, isProcessing ───────────────────

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
    // Exclude streaming fields to avoid re-rendering state consumers on every delta
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.messages, state.threadId, state.input, state.preview, state.ui, state.mode, dispatch],
  )

  const streamValue = useMemo(
    () => ({
      text: state.streaming.text,
      isProcessing: state.streaming.isProcessing,
      isSubmitting: state.streaming.isSubmitting,
    }),
    [state.streaming.text, state.streaming.isProcessing, state.streaming.isSubmitting],
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

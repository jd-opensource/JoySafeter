/**
 * useCopilotState - Unified state management hook for Copilot
 *
 * Aggregates four sub-hooks (messages, streaming, actionExecutor, session) into:
 * - state: readonly snapshot (messages, streaming, session, local UI)
 * - actions: stable object of handler functions (sub-hook methods + local setters)
 * - refs: refs for lifecycle, scroll, and URL input handling
 *
 * Note: The `actions` useMemo depends on each sub-hook's method references.
 * If a sub-hook returns new function references on every render, this useMemo
 * will re-run and may cause downstream re-renders. Prefer stable callbacks
 * in sub-hooks (useCallback with minimal deps) to avoid unnecessary churn.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'

import { useActionExecutor } from '@/hooks/copilot/useActionExecutor'
import { useCopilotMessages } from '@/hooks/copilot/useCopilotMessages'
import { useCopilotSession } from '@/hooks/copilot/useCopilotSession'
import { useCopilotStreaming, type StageType } from '@/hooks/copilot/useCopilotStreaming'

export interface CopilotState {
  // Message state
  messages: ReturnType<typeof useCopilotMessages>['messages']
  loadingHistory: boolean

  // Streaming state
  streamingContent: string
  currentStage: { stage: StageType; message: string } | null
  currentToolCall: { tool: string; input: Record<string, unknown> } | null
  toolResults: Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  expandedToolTypes: Set<string>

  // Action execution state
  executingActions: boolean

  // Session state
  currentSessionId: string | null

  // Local UI state
  input: string
  loading: boolean
  expandedItems: Set<string | number>
  copiedStreaming: boolean
}

export interface CopilotActions {
  // Message actions
  addMessage: (message: { role: 'user' | 'model'; text: string }) => void
  addThoughtStep: (step: { index: number; content: string }) => void
  clearMessages: () => void
  setThinkingMessage: () => void
  finalizeCurrentMessage: (message: string, actions?: any[]) => void
  removeCurrentMessage: () => void

  // Streaming actions
  setCurrentStage: (stage: { stage: StageType; message: string } | null) => void
  setCurrentToolCall: (call: { tool: string; input: Record<string, unknown> } | null) => void
  addToolResult: (action: { type: string; payload: Record<string, unknown>; reasoning?: string }) => void
  appendContent: (content: string) => void
  clearStreaming: () => void
  toggleToolType: (type: string) => void
  setStreamingContent: (content: string) => void

  // Action execution
  executeActions: (actions: any[]) => Promise<void>

  // Session actions
  setSession: (sessionId: string) => void
  clearSession: () => void

  // Local UI actions
  setInput: (input: string) => void
  setLoading: (loading: boolean) => void
  toggleExpand: (key: string | number) => void
  clearExpandedItems: () => void
  setCopiedStreaming: (copied: boolean) => void
}

export interface CopilotRefs {
  isMountedRef: React.MutableRefObject<boolean>
  isCreatingSessionRef: React.MutableRefObject<boolean>
  hasProcessedUrlInputRef: React.MutableRefObject<boolean>
  scrollRef: React.RefObject<HTMLDivElement | null>
  streamingContentRef: React.RefObject<HTMLDivElement | null>
  copyTimeoutRef: React.MutableRefObject<NodeJS.Timeout | null>
  lastScrollContentRef: React.MutableRefObject<string>
}

export function useCopilotState(graphId?: string) {
  // Message state
  const messagesHook = useCopilotMessages(graphId)

  // Streaming state
  const streamingHook = useCopilotStreaming()

  // Action execution state
  const actionExecutorHook = useActionExecutor()

  // Session state
  const sessionHook = useCopilotSession(graphId)

  // Local UI state
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [expandedItems, setExpandedItems] = useState<Set<string | number>>(new Set())
  const [copiedStreaming, setCopiedStreaming] = useState(false)

  // Refs for lifecycle and cleanup
  const isMountedRef = useRef(true)
  const isCreatingSessionRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const copyTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const lastScrollContentRef = useRef<string>('')

  // Set up mount status tracking and cleanup
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      // Clean up pending timeout for copy functionality
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current)
        copyTimeoutRef.current = null
      }
    }
  }, [])

  // Toggle expand helper
  const toggleExpand = useCallback((key: string | number) => {
    setExpandedItems((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  // Clear expanded items helper
  const clearExpandedItems = useCallback(() => {
    setExpandedItems(new Set())
  }, [])

  // State object
  const state: CopilotState = useMemo(() => ({
    messages: messagesHook.messages,
    loadingHistory: messagesHook.loadingHistory,
    streamingContent: streamingHook.streamingContent,
    currentStage: streamingHook.currentStage,
    currentToolCall: streamingHook.currentToolCall,
    toolResults: streamingHook.toolResults,
    expandedToolTypes: streamingHook.expandedToolTypes,
    executingActions: actionExecutorHook.executingActions,
    currentSessionId: sessionHook.currentSessionId,
    input,
    loading,
    expandedItems,
    copiedStreaming,
  }), [
    messagesHook.messages,
    messagesHook.loadingHistory,
    streamingHook.streamingContent,
    streamingHook.currentStage,
    streamingHook.currentToolCall,
    streamingHook.toolResults,
    streamingHook.expandedToolTypes,
    actionExecutorHook.executingActions,
    sessionHook.currentSessionId,
    input,
    loading,
    expandedItems,
    copiedStreaming,
  ])

  // Actions object - using stable function references
  const actions: CopilotActions = useMemo(() => ({
    ...messagesHook,
    ...streamingHook,
    ...actionExecutorHook,
    ...sessionHook,
    setInput,
    setLoading,
    toggleExpand,
    clearExpandedItems,
    setCopiedStreaming,
  }), [
    messagesHook.addMessage,
    messagesHook.addThoughtStep,
    messagesHook.clearMessages,
    messagesHook.setThinkingMessage,
    messagesHook.finalizeCurrentMessage,
    messagesHook.removeCurrentMessage,
    streamingHook.setCurrentStage,
    streamingHook.setCurrentToolCall,
    streamingHook.addToolResult,
    streamingHook.appendContent,
    streamingHook.clearStreaming,
    streamingHook.toggleToolType,
    streamingHook.setStreamingContent,
    actionExecutorHook.executeActions,
    sessionHook.setSession,
    sessionHook.clearSession,
    toggleExpand,
    clearExpandedItems,
  ])

  // Refs object
  const refs: CopilotRefs = useMemo(() => ({
    isMountedRef,
    isCreatingSessionRef,
    hasProcessedUrlInputRef: sessionHook.hasProcessedUrlInputRef,
    scrollRef,
    streamingContentRef: streamingHook.streamingContentRef,
    copyTimeoutRef,
    lastScrollContentRef,
  }), [sessionHook.hasProcessedUrlInputRef, streamingHook.streamingContentRef])

  return {
    state,
    actions,
    refs,
  }
}

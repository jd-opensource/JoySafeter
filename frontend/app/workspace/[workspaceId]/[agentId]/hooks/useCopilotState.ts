/**
 * useCopilotState - Unified state management hook for Copilot
 * 
 * This hook provides a single source of truth for all Copilot-related state,
 * encapsulating the complexity of managing multiple state domains.
 */

import { useState, useRef, useEffect, useCallback } from 'react'

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
  const state: CopilotState = {
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
  }
  
  // Actions object
  const actions: CopilotActions = {
    // Message actions
    addMessage: messagesHook.addMessage,
    addThoughtStep: messagesHook.addThoughtStep,
    clearMessages: messagesHook.clearMessages,
    setThinkingMessage: messagesHook.setThinkingMessage,
    finalizeCurrentMessage: messagesHook.finalizeCurrentMessage,
    removeCurrentMessage: messagesHook.removeCurrentMessage,
    
    // Streaming actions
    setCurrentStage: streamingHook.setCurrentStage,
    setCurrentToolCall: streamingHook.setCurrentToolCall,
    addToolResult: streamingHook.addToolResult,
    appendContent: streamingHook.appendContent,
    clearStreaming: streamingHook.clearStreaming,
    toggleToolType: streamingHook.toggleToolType,
    setStreamingContent: streamingHook.setStreamingContent,
    
    // Action execution
    executeActions: actionExecutorHook.executeActions,
    
    // Session actions
    setSession: sessionHook.setSession,
    clearSession: sessionHook.clearSession,
    
    // Local UI actions
    setInput,
    setLoading,
    toggleExpand,
    clearExpandedItems,
    setCopiedStreaming,
  }
  
  // Refs object
  const refs: CopilotRefs = {
    isMountedRef,
    isCreatingSessionRef,
    hasProcessedUrlInputRef: sessionHook.hasProcessedUrlInputRef,
    scrollRef,
    streamingContentRef: streamingHook.streamingContentRef,
    copyTimeoutRef,
    lastScrollContentRef,
  }
  
  return {
    state,
    actions,
    refs,
  }
}

/**
 * useCopilotStreaming - Hook for managing Copilot streaming state
 */

import { useState, useRef, useCallback } from 'react'

export type StageType =
  | 'thinking'
  | 'processing'
  | 'generating'
  | 'analyzing'
  | 'planning'
  | 'validating'

export function useCopilotStreaming() {
  const [streamingContent, setStreamingContent] = useState('')
  const [currentStage, setCurrentStage] = useState<{ stage: StageType; message: string } | null>(
    null,
  )
  const [currentToolCall, setCurrentToolCall] = useState<{
    tool: string
    input: Record<string, unknown>
  } | null>(null)
  const [toolResults, setToolResults] = useState<
    Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  >([])
  const [expandedToolTypes, setExpandedToolTypes] = useState<Set<string>>(new Set())
  const [copiedStreaming, setCopiedStreaming] = useState(false)
  const streamingContentRef = useRef<HTMLDivElement>(null)

  const appendContent = useCallback((content: string) => {
    setStreamingContent((prev) => {
      const normalizedContent = content.replace(/\n{2,}/g, '\n')
      let newContent: string
      if (prev.endsWith('\n') && normalizedContent.startsWith('\n')) {
        newContent = prev + normalizedContent.replace(/^\n+/, '')
      } else {
        newContent = prev + normalizedContent
      }
      return newContent.replace(/\n{2,}/g, '\n')
    })
  }, [])

  const addToolResult = useCallback(
    (action: { type: string; payload: Record<string, unknown>; reasoning?: string }) => {
      setCurrentToolCall(null)
      setToolResults((prev) => [...prev, action])
    },
    [],
  )

  const clearStreaming = useCallback(() => {
    setStreamingContent('')
    setCurrentStage(null)
    setCurrentToolCall(null)
    setToolResults([])
    setExpandedToolTypes(new Set())
  }, [])

  const toggleToolType = useCallback((type: string) => {
    setExpandedToolTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) {
        next.delete(type)
      } else {
        next.add(type)
      }
      return next
    })
  }, [])

  const setStreamingContentStable = useCallback((content: string) => {
    setStreamingContent(content)
  }, [])

  const setCurrentStageStable = useCallback(
    (stage: { stage: StageType; message: string } | null) => {
      setCurrentStage(stage)
    },
    [],
  )

  const setCurrentToolCallStable = useCallback(
    (call: { tool: string; input: Record<string, unknown> } | null) => {
      setCurrentToolCall(call)
    },
    [],
  )

  const setCopiedStreamingStable = useCallback((copied: boolean) => {
    setCopiedStreaming(copied)
  }, [])

  return {
    streamingContent,
    currentStage,
    currentToolCall,
    toolResults,
    expandedToolTypes,
    copiedStreaming,
    streamingContentRef,
    setStreamingContent: setStreamingContentStable,
    setCurrentStage: setCurrentStageStable,
    setCurrentToolCall: setCurrentToolCallStable,
    addToolResult,
    appendContent,
    clearStreaming,
    toggleToolType,
    setCopiedStreaming: setCopiedStreamingStable,
  }
}

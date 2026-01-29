/**
 * useCopilotMessages - Hook for managing Copilot messages state
 */

import { useState, useEffect, useRef } from 'react'

import { useCopilotHistory } from '@/hooks/queries/graphs'
import type { GraphAction } from '@/types/copilot'

export interface CopilotMessage {
  role: 'user' | 'model'
  text: string
  actions?: GraphAction[]
  thoughtSteps?: Array<{ index: number; content: string }>
}

export function useCopilotMessages(graphId?: string) {
  const [messages, setMessages] = useState<CopilotMessage[]>([])
  const currentMessageIndexRef = useRef<number | null>(null)
  const prevGraphIdRef = useRef<string | null>(null)

  const {
    data: historyData,
    isLoading: loadingHistory,
    isSuccess: isHistoryLoaded,
  } = useCopilotHistory(graphId)

  // Load history when graphId changes
  useEffect(() => {
    if (!graphId) return

    // Detect graphId changes and reset messages
    if (prevGraphIdRef.current && prevGraphIdRef.current !== graphId) {
      setMessages([])
      currentMessageIndexRef.current = null
    }
    prevGraphIdRef.current = graphId

    // Load history messages when data is available
    if (isHistoryLoaded && historyData?.messages && historyData.messages.length > 0) {
      const loadedMessages: CopilotMessage[] = historyData.messages.map((msg) => ({
        role: msg.role === 'user' ? 'user' : 'model',
        text: msg.content,
        actions: (msg.actions as GraphAction[]) || undefined,
        thoughtSteps: msg.thought_steps || undefined,
      }))

      setMessages(loadedMessages)
    }
  }, [graphId, isHistoryLoaded, historyData])

  const addMessage = (message: CopilotMessage) => {
    setMessages((prev) => [...prev, message])
  }

  const updateCurrentMessage = (updates: Partial<CopilotMessage>) => {
    setMessages((prev) => {
      const newMessages = [...prev]
      if (currentMessageIndexRef.current !== null && newMessages[currentMessageIndexRef.current]) {
        newMessages[currentMessageIndexRef.current] = {
          ...newMessages[currentMessageIndexRef.current],
          ...updates,
        }
      }
      return newMessages
    })
  }

  const addThoughtStep = (step: { index: number; content: string }) => {
    setMessages((prev) => {
      const newMessages = [...prev]
      if (currentMessageIndexRef.current !== null && newMessages[currentMessageIndexRef.current]) {
        const currentMessage = newMessages[currentMessageIndexRef.current]
        const existingSteps = currentMessage.thoughtSteps || []
        const stepExists = existingSteps.some((s) => s.index === step.index)
        if (!stepExists) {
          newMessages[currentMessageIndexRef.current] = {
            ...currentMessage,
            thoughtSteps: [...existingSteps, step],
          }
        }
      }
      return newMessages
    })
  }

  const clearMessages = () => {
    setMessages([])
    currentMessageIndexRef.current = null
  }

  const setThinkingMessage = () => {
    setMessages((prev) => {
      const newMessages = [...prev]
      currentMessageIndexRef.current = newMessages.length
      newMessages.push({
        role: 'model',
        text: '',
        thoughtSteps: [],
      })
      return newMessages
    })
  }

  const finalizeCurrentMessage = (message: string, actions?: GraphAction[]) => {
    setMessages((prev) => {
      const newMessages = [...prev]
      if (currentMessageIndexRef.current !== null && newMessages[currentMessageIndexRef.current]) {
        const currentMessage = newMessages[currentMessageIndexRef.current]
        newMessages[currentMessageIndexRef.current] = {
          role: 'model',
          text: message,
          actions,
          thoughtSteps: currentMessage.thoughtSteps,
        }
      } else {
        newMessages.push({
          role: 'model',
          text: message,
          actions,
        })
      }
      currentMessageIndexRef.current = null
      return newMessages
    })
  }

  const removeCurrentMessage = () => {
    if (currentMessageIndexRef.current !== null) {
      setMessages((prev) => prev.filter((_, idx) => idx !== currentMessageIndexRef.current))
      currentMessageIndexRef.current = null
    }
  }

  return {
    messages,
    loadingHistory,
    currentMessageIndexRef,
    addMessage,
    updateCurrentMessage,
    addThoughtStep,
    clearMessages,
    setThinkingMessage,
    finalizeCurrentMessage,
    removeCurrentMessage,
    setMessages,
  }
}

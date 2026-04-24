/**
 * useCopilotMessages - Hook for managing Copilot messages state
 */

import { useState, useEffect, useRef, useCallback } from 'react'

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

  // Reset messages when graphId changes
  useEffect(() => {
    if (!graphId) return

    if (prevGraphIdRef.current && prevGraphIdRef.current !== graphId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([])
      currentMessageIndexRef.current = null
    }
    prevGraphIdRef.current = graphId
  }, [graphId])

  const addMessage = useCallback((message: CopilotMessage) => {
    setMessages((prev) => [...prev, message])
  }, [])

  const addThoughtStep = useCallback((step: { index: number; content: string }) => {
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
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    currentMessageIndexRef.current = null
  }, [])

  const setThinkingMessage = useCallback(() => {
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
  }, [])

  const finalizeCurrentMessage = useCallback((message: string, actions?: GraphAction[]) => {
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
  }, [])

  const removeCurrentMessage = useCallback(() => {
    if (currentMessageIndexRef.current !== null) {
      setMessages((prev) => prev.filter((_, idx) => idx !== currentMessageIndexRef.current))
      currentMessageIndexRef.current = null
    }
  }, [])

  return {
    messages,
    loadingHistory: false,
    currentMessageIndexRef,
    addMessage,
    addThoughtStep,
    clearMessages,
    setThinkingMessage,
    finalizeCurrentMessage,
    removeCurrentMessage,
    setMessages,
  }
}

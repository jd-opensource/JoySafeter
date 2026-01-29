/**
 * useCopilotEffects - Side effects hook for Copilot
 *
 * Handles all useEffect logic: session recovery, auto-scroll, URL parameters, etc.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams, useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { graphKeys } from '@/hooks/queries/graphs'
import { copilotService } from '@/services/copilotService'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

interface UseCopilotEffectsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
  handleSendWithInput: (input: string) => Promise<void>
}

/**
 * Helper function to check if there's a current message being streamed
 */
function hasCurrentMessage(messages: Array<{ role: string; text?: string }>, checkEmptyText = true): boolean {
  if (messages.length === 0) return false
  const lastMessage = messages[messages.length - 1]
  if (lastMessage.role !== 'model') return false
  if (checkEmptyText && lastMessage.text) return false
  return true
}

export function useCopilotEffects({
  state,
  actions,
  refs,
  graphId,
  handleSendWithInput,
}: UseCopilotEffectsOptions) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const queryClient = useQueryClient()

  // Session recovery: restore state and content when sessionId is restored
  useEffect(() => {
    const { currentSessionId } = state
    if (!currentSessionId || refs.isCreatingSessionRef.current) {
      return
    }

    const restoreSession = async () => {
      try {
        const sessionData = await copilotService.getSession(currentSessionId)

        if (!refs.isMountedRef.current) return

        if (sessionData?.status === 'generating') {
          actions.setLoading(true)

          if (sessionData.content) {
            actions.setStreamingContent(sessionData.content)
            actions.setCurrentStage({ stage: 'processing', message: '继续处理中...' })

            if (!hasCurrentMessage(state.messages, false)) {
              actions.setThinkingMessage()
            }
          }
        } else {
          if (refs.isMountedRef.current) {
            actions.setLoading(false)
          }
        }
      } catch (error) {
        console.warn('[CopilotPanel] Failed to restore session:', error)
        if (refs.isMountedRef.current) {
          actions.setLoading(false)
        }
      }
    }

    restoreSession()
  }, [
    state.currentSessionId,
    state.messages,
    actions,
    refs,
  ])

  // Update page title to show loading status
  useEffect(() => {
    const baseTitle = 'Agent Platform'
    if (state.loading && state.currentStage) {
      document.title = `⏳ ${state.currentStage.message} - ${baseTitle}`
    } else {
      document.title = baseTitle
    }
  }, [state.loading, state.currentStage])

  // Auto-scroll to bottom when content changes
  useEffect(() => {
    if (!refs.scrollRef.current) return

    // Create a content signature to detect actual changes
    const contentSignature = `${state.messages.length}-${state.streamingContent.length}-${state.loading}`
    if (contentSignature === refs.lastScrollContentRef.current) {
      return // No actual content change, skip scrolling
    }
    refs.lastScrollContentRef.current = contentSignature

    // Use requestAnimationFrame to ensure DOM is updated before scrolling
    requestAnimationFrame(() => {
      if (!refs.isMountedRef.current || !refs.scrollRef.current) return

      refs.scrollRef.current.scrollTo({
        top: refs.scrollRef.current.scrollHeight,
        behavior: state.streamingContent ? 'smooth' : 'auto'
      })

      // Also scroll streaming content container if it has its own scroll
      if (refs.streamingContentRef.current) {
        refs.streamingContentRef.current.scrollTo({
          top: refs.streamingContentRef.current.scrollHeight,
          behavior: 'smooth'
        })
      }
    })
  }, [state.messages, state.loading, state.streamingContent, refs])

  // Warn user before leaving page during generation
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (state.loading || state.executingActions) {
        e.preventDefault()
        e.returnValue = ''
        return ''
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [state.loading, state.executingActions])

  // Handle URL parameter for auto-executing copilot input
  useEffect(() => {
    const copilotInput = searchParams.get('copilotInput')

    if (copilotInput && !refs.hasProcessedUrlInputRef.current && !state.loading) {
      refs.hasProcessedUrlInputRef.current = true

      const decodedInput = decodeURIComponent(copilotInput)

      // Clean up URL parameter first
      const params = new URLSearchParams(searchParams.toString())
      params.delete('copilotInput')
      const newSearch = params.toString()
      const newUrl = newSearch
        ? `${window.location.pathname}?${newSearch}`
        : window.location.pathname
      router.replace(newUrl, { scroll: false })

      // Set input and trigger send after a short delay
      let timeout1: NodeJS.Timeout | null = null
      let timeout2: NodeJS.Timeout | null = null

      timeout1 = setTimeout(() => {
        if (!refs.isMountedRef.current) return
        actions.setInput(decodedInput)
        timeout2 = setTimeout(() => {
          if (!refs.isMountedRef.current) return
          handleSendWithInput(decodedInput)
        }, 100)
      }, 300)

      return () => {
        if (timeout1) clearTimeout(timeout1)
        if (timeout2) clearTimeout(timeout2)
      }
    }
  }, [searchParams, state.loading, router, actions, refs, handleSendWithInput])
}

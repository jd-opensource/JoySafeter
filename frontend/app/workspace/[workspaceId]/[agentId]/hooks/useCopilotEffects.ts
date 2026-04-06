/**
 * useCopilotEffects - Side effects hook for Copilot
 *
 * Handles UI side effects: page title, auto-scroll, URL parameter cleanup.
 * Session restoration is handled by useCopilotSession (init) and this hook (fetch).
 */

import { useSearchParams, useRouter } from 'next/navigation'
import { useEffect, useRef } from 'react'

import { useToast } from '@/hooks/use-toast'
import { copilotService } from '@/services/copilotService'

import { hasCurrentMessage } from '../utils/copilotUtils'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

interface UseCopilotEffectsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
  handleSendWithInput: (input: string) => Promise<void>
}

export function useCopilotEffects({
  state,
  actions,
  refs,
  handleSendWithInput,
}: UseCopilotEffectsOptions) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const { toast } = useToast()
  const lastRestoredSessionIdRef = useRef<string | null>(null)

  // Session recovery: restore state and content when sessionId is restored
  useEffect(() => {
    const currentRunId = state.currentRunId
    if (
      !currentRunId ||
      refs.isCreatingSessionRef.current ||
      lastRestoredSessionIdRef.current === currentRunId
    )
      return

    const restoreSession = async () => {
      console.warn('[useCopilotEffects] Restoring from run snapshot:', currentRunId)
      lastRestoredSessionIdRef.current = currentRunId

      try {
        actions.setLoading(true)
        const sessionData = await copilotService.getSession(currentRunId)
        if (!refs.isMountedRef.current) return

        if (!sessionData || sessionData.status == null) {
          actions.clearSession()
          return
        }

        if (sessionData.status === 'generating') {
          if (sessionData.result?.actions?.length) {
            await actions.executeActions(sessionData.result.actions)
            actions.finalizeCurrentMessage(
              sessionData.result.message ?? '',
              sessionData.result.actions,
            )
          } else if (sessionData.content) {
            actions.setStreamingContent(sessionData.content)
            actions.setCurrentStage({ stage: 'processing', message: 'Processing...' })
            if (!hasCurrentMessage(state.messages, false)) actions.setThinkingMessage()
          }
        } else if (sessionData.status === 'completed') {
          actions.clearSession()
          actions.clearStreaming()
        } else if (sessionData.status === 'failed') {
          toast({
            title: 'Copilot task failed',
            description: sessionData.error || 'An error occurred during execution. Please retry.',
            variant: 'destructive',
          })
          actions.clearSession()
        }
      } catch (error) {
        console.warn('[CopilotPanel] Failed to restore session:', error)
      } finally {
        if (refs.isMountedRef.current) actions.setLoading(false)
      }
    }

    restoreSession()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.currentRunId, actions, refs])

  // Update page title to show loading status
  useEffect(() => {
    const baseTitle = 'Agent Platform'
    document.title =
      state.loading && state.currentStage
        ? `⏳ ${state.currentStage.message} - ${baseTitle}`
        : baseTitle
  }, [state.loading, state.currentStage])

  // Auto-scroll to bottom when content changes
  useEffect(() => {
    const scrollEl = refs.scrollRef.current
    if (!scrollEl) return

    const contentSignature = `${state.messages.length}-${state.streamingContent.length}-${state.loading}`
    if (contentSignature === refs.lastScrollContentRef.current) return
    refs.lastScrollContentRef.current = contentSignature

    requestAnimationFrame(() => {
      if (!refs.isMountedRef.current || !scrollEl) return
      scrollEl.scrollTo({
        top: scrollEl.scrollHeight,
        behavior: state.streamingContent ? 'smooth' : 'auto',
      })
      if (refs.streamingContentRef.current) {
        refs.streamingContentRef.current.scrollTo({
          top: refs.streamingContentRef.current.scrollHeight,
          behavior: 'smooth',
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
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [state.loading, state.executingActions])

  // Handle URL parameter for auto-executing copilot input
  useEffect(() => {
    const copilotInput = searchParams.get('copilotInput')
    if (!copilotInput || refs.hasProcessedUrlInputRef.current || state.loading) return

    refs.hasProcessedUrlInputRef.current = true
    const decodedInput = decodeURIComponent(copilotInput)
    const params = new URLSearchParams(searchParams.toString())
    params.delete('copilotInput')
    const newSearch = params.toString()
    router.replace(
      newSearch ? `${window.location.pathname}?${newSearch}` : window.location.pathname,
      { scroll: false },
    )

    setTimeout(() => {
      if (!refs.isMountedRef.current) return
      actions.setInput(decodedInput)
      setTimeout(() => {
        if (refs.isMountedRef.current) handleSendWithInput(decodedInput)
      }, 100)
    }, 300)
  }, [searchParams, state.loading, router, actions, refs, handleSendWithInput])
}

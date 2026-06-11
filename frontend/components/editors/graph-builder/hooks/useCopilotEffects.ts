import { useSearchParams, useRouter } from 'next/navigation'
import { useEffect, useRef } from 'react'

import { useToast } from '@/hooks/use-toast'
import { createLogger } from '@/lib/logs/console/logger'
import { agentRunService } from '@/services/agentRunService'

import { useGraphStore } from '../stores/graphStore'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

const logger = createLogger('DraftCopilotEffects')

interface CopilotSearchParams {
  get: (name: string) => string | null
}

export function getCopilotInputFromSearchParams(searchParams: CopilotSearchParams): string | null {
  return searchParams.get('copilotInput')
}

interface UseCopilotEffectsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
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

  useEffect(() => {
    const currentRunId = state.currentRunId
    if (
      !currentRunId ||
      refs.isCreatingSessionRef.current ||
      lastRestoredSessionIdRef.current === currentRunId
    )
      return

    const restoreSession = async () => {
      logger.debug('Restoring from run:', currentRunId)
      lastRestoredSessionIdRef.current = currentRunId

      try {
        actions.setLoading(true)
        const run = await agentRunService.get(currentRunId)
        if (!refs.isMountedRef.current) return

        if (run.status === 'running' || run.status === 'pending') {
          // Set executionId — the bridge (useCopilotExecutionBridge) automatically
          // subscribes via /ws/executions, receives snapshot + replay + live events
          if (run.current_execution_id) {
            actions.setSession(currentRunId, run.current_execution_id)
          }
          actions.setCurrentStage({ stage: 'processing', message: 'Reconnecting...' })
        } else if (run.status === 'succeeded') {
          actions.clearSession()
          actions.setLoading(false)
        } else if (run.status === 'failed') {
          toast({
            title: 'Build Copilot task failed',
            description: run.result_summary || 'An error occurred during execution. Please retry.',
            variant: 'destructive',
          })
          actions.clearSession()
          actions.setLoading(false)
        } else {
          actions.clearSession()
          actions.setLoading(false)
        }
      } catch (error) {
        logger.warn('Failed to restore session:', error)
        if (refs.isMountedRef.current) {
          actions.clearSession()
          actions.setLoading(false)
        }
      }
    }

    restoreSession()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.currentRunId, actions, refs])

  // Reconnect to active run on mount when localStorage is empty.
  // Delayed so useCopilotSession's localStorage read settles first — otherwise
  // this effect and the restore effect race on an empty state.
  useEffect(() => {
    if (state.currentRunId || refs.isCreatingSessionRef.current) return

    const { agentId, projectId } = useGraphStore.getState()
    if (!agentId || !projectId) return

    const timer = setTimeout(() => {
      if (lastRestoredSessionIdRef.current || !refs.isMountedRef.current) return

      agentRunService
        .list({
          agent_id: agentId,
          trigger_medium: 'ui',
          run_purpose: 'internal_builder',
          status: 'running',
        })
        .then((runs) => {
          if (!refs.isMountedRef.current || runs.length === 0) return
          if (lastRestoredSessionIdRef.current) return
          const activeRun = runs[0]
          if (activeRun.current_execution_id) {
            actions.setSession(activeRun.id, activeRun.current_execution_id)
          }
        })
        .catch((err) => {
          logger.debug('Failed to check for active draft copilot run:', err)
        })
    }, 50)

    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    const copilotInput = getCopilotInputFromSearchParams(searchParams)
    if (!copilotInput || refs.hasProcessedUrlInputRef.current || state.loading) return

    refs.hasProcessedUrlInputRef.current = true
    const params = new URLSearchParams(searchParams.toString())
    params.delete('copilotInput')
    const newSearch = params.toString()
    router.replace(
      newSearch ? `${window.location.pathname}?${newSearch}` : window.location.pathname,
      { scroll: false },
    )

    setTimeout(() => {
      if (!refs.isMountedRef.current) return
      actions.setInput(copilotInput)
      setTimeout(() => {
        if (refs.isMountedRef.current) handleSendWithInput(copilotInput)
      }, 100)
    }, 300)
  }, [searchParams, state.loading, router, actions, refs, handleSendWithInput])
}

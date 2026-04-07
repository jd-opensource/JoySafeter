/**
 * useCopilotEffects - Side effects hook for Copilot
 *
 * Handles UI side effects: page title, auto-scroll, URL parameter cleanup.
 * Run restoration is handled by useCopilotSession (init) and this hook (fetch via Run Center).
 */

import { useSearchParams, useRouter } from 'next/navigation'
import { useEffect, useRef } from 'react'

import { useToast } from '@/hooks/use-toast'
import { createLogger } from '@/lib/logs/console/logger'
import type { RunEventFrame, RunStatusFrame } from '@/lib/ws/runs/types'
import { getRunWsClient } from '@/lib/ws/runs/runWsClient'
import type { ChatStreamEvent } from '@/services/chatBackend'
import { runService } from '@/services/runService'

import { hasCurrentMessage } from '../utils/copilotUtils'

import type { CopilotState, CopilotActions, CopilotRefs } from './useCopilotState'

const logger = createLogger('CopilotEffects')

interface UseCopilotEffectsOptions {
  state: CopilotState
  actions: CopilotActions
  refs: CopilotRefs
  graphId?: string
  handleSendWithInput: (input: string) => Promise<void>
  handleCopilotEvent: (evt: ChatStreamEvent) => void
}

/** Map a persisted RunEventFrame back to the ChatStreamEvent shape that handleCopilotEvent expects. */
function runEventToChatEvent(frame: RunEventFrame): ChatStreamEvent {
  // _mirror_run_stream_event stores "content" as "content_delta"; reverse it
  const type = frame.event_type === 'content_delta' ? 'content' : frame.event_type
  return { type, data: frame.data } as ChatStreamEvent
}

export function useCopilotEffects({
  state,
  actions,
  refs,
  handleSendWithInput,
  handleCopilotEvent,
}: UseCopilotEffectsOptions) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const { toast } = useToast()
  const lastRestoredSessionIdRef = useRef<string | null>(null)
  const activeSubscriptionRef = useRef<string | null>(null)

  // Cleanup run subscription on unmount
  useEffect(() => {
    return () => {
      if (activeSubscriptionRef.current) {
        getRunWsClient().unsubscribe(activeSubscriptionRef.current)
        activeSubscriptionRef.current = null
      }
    }
  }, [])

  // Session recovery: restore state from run snapshot when runId is restored
  useEffect(() => {
    const currentRunId = state.currentRunId
    if (
      !currentRunId ||
      refs.isCreatingSessionRef.current ||
      lastRestoredSessionIdRef.current === currentRunId
    )
      return

    const restoreSession = async () => {
      logger.debug('Restoring from run snapshot:', currentRunId)
      lastRestoredSessionIdRef.current = currentRunId

      try {
        actions.setLoading(true)
        const snapshot = await runService.getRunSnapshot(currentRunId)
        if (!refs.isMountedRef.current) return

        if (!snapshot) {
          actions.clearSession()
          return
        }

        const projection = snapshot.projection as Record<string, unknown> | undefined
        const status = snapshot.status as string

        if (status === 'running' || status === 'queued') {
          // Run still active -- show last known state from snapshot
          if (projection) {
            const content = projection.content as string | undefined
            if (content) {
              actions.setStreamingContent(content)
            }
            const stage = projection.stage as string | undefined
            actions.setCurrentStage({ stage: (stage || 'processing') as any, message: 'Processing...' })
            if (!hasCurrentMessage(state.messages, false)) actions.setThinkingMessage()
          }

          // Subscribe to /ws/runs for live event replay from where snapshot left off
          const afterSeq = snapshot.last_seq ?? 0
          activeSubscriptionRef.current = currentRunId
          getRunWsClient()
            .subscribe(currentRunId, afterSeq, {
              onEvent: (frame: RunEventFrame) => {
                if (!refs.isMountedRef.current) return
                handleCopilotEvent(runEventToChatEvent(frame))
              },
              onStatus: (frame: RunStatusFrame) => {
                if (!refs.isMountedRef.current) return
                if (frame.status === 'completed' || frame.status === 'failed') {
                  getRunWsClient().unsubscribe(currentRunId)
                  activeSubscriptionRef.current = null
                  // Re-fetch final snapshot to get complete projection
                  runService.getRunSnapshot(currentRunId).then((finalSnapshot) => {
                    if (!refs.isMountedRef.current || !finalSnapshot) return
                    const fp = finalSnapshot.projection as Record<string, unknown> | undefined
                    if (frame.status === 'completed' && fp) {
                      const resultMessage = (fp.result_message as string) ?? ''
                      const resultActions = fp.result_actions as Array<Record<string, unknown>> | undefined
                      actions.clearStreaming()
                      actions.finalizeCurrentMessage(resultMessage, resultActions as any)
                      if (resultActions && resultActions.length > 0) {
                        actions.executeActions(resultActions as any)
                      }
                    } else if (frame.status === 'failed') {
                      actions.clearStreaming()
                      actions.finalizeCurrentMessage(
                        (fp?.error as string) || frame.error_message || 'Copilot task failed',
                      )
                    }
                    actions.clearSession()
                    actions.setLoading(false)
                  }).catch(() => {
                    actions.clearSession()
                    actions.setLoading(false)
                  })
                }
              },
              onError: (message: string) => {
                logger.warn('Run subscription error:', message)
              },
            })
            .catch((err) => {
              logger.warn('Failed to subscribe to run events:', err)
            })
        } else if (status === 'completed') {
          if (projection) {
            const resultMessage = (projection.result_message as string) ?? ''
            const resultActions = projection.result_actions as Array<Record<string, unknown>> | undefined
            if (resultMessage || (resultActions && resultActions.length > 0)) {
              actions.finalizeCurrentMessage(resultMessage, resultActions as any)
            }
          }
          actions.clearSession()
          actions.clearStreaming()
        } else if (status === 'failed') {
          toast({
            title: 'Copilot task failed',
            description: (projection?.error as string) || 'An error occurred during execution. Please retry.',
            variant: 'destructive',
          })
          actions.clearSession()
        }
      } catch (error) {
        logger.warn('Failed to restore from run snapshot:', error)
      } finally {
        if (refs.isMountedRef.current) actions.setLoading(false)
      }
    }

    restoreSession()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.currentRunId, actions, refs, handleCopilotEvent])

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

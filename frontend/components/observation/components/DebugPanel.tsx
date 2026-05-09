'use client'

import { useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationStream } from '../hooks/useObservationStream'
import { DebugToolbar } from './DebugToolbar'
import { ObservationNavigation } from './ObservationNavigation'
import { ObservationDetailPanel } from './ObservationDetailPanel'
import { ObservationProviders } from './ObservationProviders'
import { TurnTimeline } from './TurnTimeline'
import { normalizeObservation } from '../lib/normalize'
import { Toolbar } from '../ObservationPanel'
import { apiGet, apiPost } from '@/lib/api-client'
import { useArchiveThread, useCreateThread } from '@/hooks/queries/threads'

interface DebugPanelProps {
  agentId: string
  agentVersionId: string
  workspaceId: string
}

type PanelMode = 'idle' | 'live' | 'replay'

function DebugPanelInner({ agentId, agentVersionId, workspaceId }: DebugPanelProps) {
  const [executionId, setExecutionId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [mode, setMode] = useState<PanelMode>('idle')
  const [replayTraceId, setReplayTraceId] = useState<string | null>(null)

  // Session state — a Thread is provisioned on mount and lives for the
  // entire panel session. "New Session" archives it and provisions a fresh one.
  const [threadId, setThreadId] = useState<string | null>(null)
  const [turnCount, setTurnCount] = useState(0)

  // activeTraceId is derived — in live mode it's the streaming execution,
  // in replay mode whichever trace the timeline selected, otherwise none.
  const activeTraceId = mode === 'live' ? executionId : mode === 'replay' ? replayTraceId : null

  const { dispatch, loadTrace, isExecuting } = useObservationData()
  useObservationStream(mode === 'live' ? executionId : null)

  const queryClient = useQueryClient()
  const createThread = useCreateThread()
  const archiveThread = useArchiveThread()

  // Provision a Thread on mount (and after "New Session"). The mutation fires
  // when threadId is null; we swallow the promise because useMutation already
  // tracks in-flight state via isPending and caller-side StrictMode re-runs.
  useEffect(() => {
    if (threadId || createThread.isPending) return
    createThread
      .mutateAsync({ agent_id: agentId, title: `Debug session – ${new Date().toLocaleString()}`, workspace_id: workspaceId })
      .then((thread) => setThreadId(thread.id))
      .catch((err) => console.error('DebugPanel: thread provisioning failed', err))
    // mutate* identities from useMutation are stable; we only need to react to
    // threadId flipping to null (new session) or inputs changing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, agentId, workspaceId])

  const tracesQueryKey = ['traces', agentVersionId, workspaceId, threadId] as const
  const { data: traces = [] } = useQuery({
    queryKey: tracesQueryKey,
    queryFn: async () => {
      const sessionFilter = threadId ? `&session_id=${threadId}` : ''
      const data = await apiGet<Array<{ id: string; created_at: string }>>(
        `/traces?workspace_id=${workspaceId}&agent_version_id=${agentVersionId}&page_size=20${sessionFilter}`,
      )
      return data.map((t) => ({ id: t.id, createdAt: t.created_at }))
    },
    enabled: !!agentVersionId && !!workspaceId && !!threadId,
  })

  const { data: replayObservations } = useQuery({
    queryKey: ['trace-observations', replayTraceId],
    queryFn: async () => {
      const rawList = await apiGet<Record<string, unknown>[]>(
        `/traces/${replayTraceId}/observations`,
      )
      return rawList.map(normalizeObservation)
    },
    enabled: mode === 'replay' && !!replayTraceId,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    gcTime: 0,
  })

  useEffect(() => {
    if (!replayObservations || replayObservations.length === 0) return
    const traceStart = new Date(
      Math.min(...replayObservations.map((o) => new Date(o.startTime).getTime())),
    )
    loadTrace(replayObservations, traceStart)
  }, [replayObservations, loadTrace])

  const handleStartDebug = useCallback(
    async (prompt: string) => {
      if (!threadId) {
        console.warn('DebugPanel: thread not yet ready; ignoring start')
        return
      }
      // Clear the live observation tree so the next turn starts with a fresh
      // view; prior turns remain accessible via the TurnTimeline.
      dispatch({ type: 'RESET' })

      try {
        const data = await apiPost<{ execution_id: string; run_id: string }>('/executions/debug', {
          agent_id: agentId,
          agent_version_id: agentVersionId,
          prompt,
          workspace_id: workspaceId,
          thread_id: threadId,
        })
        setExecutionId(data.execution_id)
        setRunId(data.run_id)
        setMode('live')
        setTurnCount((c) => c + 1)

        // Trace is inserted in the engine's session (after dispatch returns),
        // so the /traces list won't include it yet. Invalidate to refetch —
        // react-query re-requests as soon as the new row is visible.
        queryClient.invalidateQueries({ queryKey: tracesQueryKey })
      } catch (err) {
        console.error('Debug start failed:', err)
      }
    },
    [agentId, agentVersionId, workspaceId, threadId, dispatch, queryClient, tracesQueryKey],
  )

  const handleStop = useCallback(async () => {
    if (!runId) return
    await apiPost(`/agent-runs/${runId}/cancel`)
  }, [runId])

  const handleSelectTrace = useCallback(
    (traceId: string) => {
      dispatch({ type: 'RESET' })
      setReplayTraceId(traceId)
      setMode('replay')
    },
    [dispatch],
  )

  const handleNewSession = useCallback(() => {
    if (threadId) {
      archiveThread.mutate({ threadId, workspaceId })
    }
    dispatch({ type: 'RESET' })
    setThreadId(null)
    setTurnCount(0)
    setExecutionId(null)
    setRunId(null)
    setMode('idle')
    setReplayTraceId(null)
  }, [threadId, workspaceId, dispatch, archiveThread])

  // traces come from the API in DESC order (newest first). Reverse inline —
  // ≤20 items per session, not worth a useMemo.
  const timelineTurns = [...traces].reverse()

  return (
    <div className="flex h-full flex-col">
      <DebugToolbar
        isExecuting={isExecuting}
        onStartDebug={handleStartDebug}
        onStop={handleStop}
        turnCount={turnCount}
        onNewSession={handleNewSession}
      />
      <TurnTimeline
        turns={timelineTurns}
        activeTraceId={activeTraceId}
        isLive={mode === 'live'}
        onSelect={handleSelectTrace}
      />
      <Toolbar />
      <PanelGroup direction="horizontal" className="flex-1">
        <Panel defaultSize={40} minSize={20} collapsible collapsedSize={3}>
          <ObservationNavigation />
        </Panel>
        <PanelResizeHandle className="hover:bg-primary-accent/50 w-px bg-border transition-colors" />
        <Panel defaultSize={60} minSize={30}>
          <ObservationDetailPanel />
        </Panel>
      </PanelGroup>
    </div>
  )
}

export function DebugPanel(props: DebugPanelProps) {
  return (
    <ObservationProviders>
      <DebugPanelInner {...props} />
    </ObservationProviders>
  )
}

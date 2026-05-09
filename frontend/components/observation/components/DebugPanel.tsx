'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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
import { threadService } from '@/services/threadService'

interface DebugPanelProps {
  agentId: string
  agentVersionId: string
  workspaceId: string
}

function DebugPanelInner({ agentId, agentVersionId, workspaceId }: DebugPanelProps) {
  const [executionId, setExecutionId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [mode, setMode] = useState<'idle' | 'live' | 'replay'>('idle')
  const [replayTraceId, setReplayTraceId] = useState<string | null>(null)

  // Session state — a Thread is provisioned on mount and lives for the
  // entire panel session. "New Session" archives it and provisions a fresh one.
  const [threadId, setThreadId] = useState<string | null>(null)
  const [turnCount, setTurnCount] = useState(0)
  // Which turn's trace is currently shown in the observation panel. Kept in
  // sync with mode: in live mode it's the streaming execution, in replay it's
  // whichever turn the user clicked in the timeline.
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)

  const { dispatch, loadTrace, isExecuting } = useObservationData()
  useObservationStream(mode === 'live' ? executionId : null)

  // Provision a Thread on mount (and after "New Session"). Every debug turn
  // flows through this thread, so the backend pool + Trace aggregation stay
  // consistent. The thread is archived on "New Session".
  useEffect(() => {
    if (threadId) return
    let cancelled = false
    threadService
      .create({
        agent_id: agentId,
        title: `Debug session – ${new Date().toLocaleString()}`,
        workspace_id: workspaceId,
      })
      .then((thread) => {
        if (!cancelled) setThreadId(thread.id)
      })
      .catch((err) => {
        console.error('DebugPanel: thread provisioning failed', err)
      })
    return () => {
      cancelled = true
    }
  }, [threadId, agentId, workspaceId])

  const { data: traces = [], refetch: refetchTraces } = useQuery({
    queryKey: ['traces', agentVersionId, workspaceId, threadId],
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
      // Clear the live observation tree so the next turn starts with a fresh view;
      // prior turns remain accessible in the History dropdown via session filtering.
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
        // The new trace's id == execution_id — that lets the timeline highlight
        // the in-flight turn before the /traces list refetch completes.
        setActiveTraceId(data.execution_id)
        setTurnCount((c) => c + 1)

        // Trace row is created during _fire_engine; give it a tick before
        // surfacing the new entry in the history dropdown.
        setTimeout(() => refetchTraces(), 1000)
      } catch (err) {
        console.error('Debug start failed:', err)
      }
    },
    [agentId, agentVersionId, workspaceId, threadId, dispatch, refetchTraces],
  )

  const handleStop = useCallback(async () => {
    if (!runId) return
    await apiPost(`/agent-runs/${runId}/cancel`)
  }, [runId])

  const handleSelectTrace = useCallback(
    (traceId: string) => {
      dispatch({ type: 'RESET' })
      setReplayTraceId(traceId)
      setActiveTraceId(traceId)
      setMode('replay')
    },
    [dispatch],
  )

  const handleNewSession = useCallback(() => {
    // Archive old thread
    if (threadId) {
      threadService.archive(threadId, workspaceId).catch(() => {})
    }
    // Reset all state for a fresh session
    dispatch({ type: 'RESET' })
    setThreadId(null)
    setTurnCount(0)
    setExecutionId(null)
    setRunId(null)
    setMode('idle')
    setReplayTraceId(null)
    setActiveTraceId(null)
  }, [threadId, workspaceId, dispatch])

  // traces come from the API in DESC order (newest first). The timeline
  // renders chronologically so Turn 1 is leftmost; reverse once here.
  const timelineTurns = useMemo(
    () => [...traces].reverse().map((t) => ({ id: t.id, createdAt: t.createdAt })),
    [traces],
  )

  return (
    <div className="flex h-full flex-col">
      <DebugToolbar
        agentId={agentId}
        agentVersionId={agentVersionId}
        workspaceId={workspaceId}
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

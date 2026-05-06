'use client'

import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationStream } from '../hooks/useObservationStream'
import { DebugToolbar } from './DebugToolbar'
import { ObservationNavigation } from './ObservationNavigation'
import { ObservationDetailPanel } from './ObservationDetailPanel'
import { ObservationProviders } from './ObservationProviders'
import { normalizeObservation } from '../lib/normalize'
import { Toolbar } from '../ObservationPanel'
import { apiGet, apiPost } from '@/lib/api-client'

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

  const { dispatch, loadTrace, isExecuting } = useObservationData()
  useObservationStream(mode === 'live' ? executionId : null)

  const { data: traces = [] } = useQuery({
    queryKey: ['traces', agentVersionId, workspaceId],
    queryFn: async () => {
      const data = await apiGet<Array<{ id: string; created_at: string }>>(
        `/traces?workspace_id=${workspaceId}&agent_version_id=${agentVersionId}&page_size=20`,
      )
      return data.map((t) => ({ id: t.id, createdAt: t.created_at }))
    },
    enabled: !!agentVersionId && !!workspaceId,
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
      dispatch({ type: 'RESET' })
      try {
        const data = await apiPost<{ execution_id: string; run_id: string }>('/executions/debug', {
          agent_id: agentId,
          agent_version_id: agentVersionId,
          prompt,
          workspace_id: workspaceId,
        })
        setExecutionId(data.execution_id)
        setRunId(data.run_id)
        setMode('live')
      } catch (err) {
        console.error('Debug start failed:', err)
      }
    },
    [agentId, agentVersionId, workspaceId, dispatch],
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

  return (
    <div className="flex h-full flex-col">
      <DebugToolbar
        agentId={agentId}
        agentVersionId={agentVersionId}
        workspaceId={workspaceId}
        isExecuting={isExecuting}
        onStartDebug={handleStartDebug}
        onStop={handleStop}
        onSelectTrace={handleSelectTrace}
        traces={traces}
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

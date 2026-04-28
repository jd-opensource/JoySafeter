'use client'

import { Suspense, useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationStream } from '../hooks/useObservationStream'
import { DebugToolbar } from './DebugToolbar'
import { ObservationNavigation } from './ObservationNavigation'
import { ObservationDetailPanel } from './ObservationDetailPanel'
import { ObservationViewPrefsProvider } from '../contexts/ObservationViewPrefsContext'
import { ObservationDataProvider } from '../contexts/ObservationDataContext'
import { ObservationSelectionProvider } from '../contexts/ObservationSelectionContext'
import { ObservationJsonExpansionProvider } from '../contexts/ObservationJsonExpansionContext'
import { normalizeObservation } from '../lib/normalize'
import { Toolbar } from '../ObservationPanel'
import { apiGet, apiPost } from '@/lib/api-client'
import type { RawObservation } from '../lib/types'

interface DebugPanelProps {
  agentId: string
  agentVersionId: string
  workspaceId: string
}

function DebugPanelInner({
  agentId,
  agentVersionId,
  workspaceId,
}: DebugPanelProps) {
  const [executionId, setExecutionId] = useState<string | null>(null)
  const [mode, setMode] = useState<'idle' | 'live' | 'replay'>('idle')
  const [replayTraceId, setReplayTraceId] = useState<string | null>(null)

  const { dispatch, loadTrace, isExecuting } = useObservationData()
  useObservationStream(
    mode === 'live' ? executionId : null,
  )

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
        const data = await apiPost<{ execution_id: string }>(
          '/executions/debug',
          {
            agent_id: agentId,
            agent_version_id: agentVersionId,
            prompt,
            workspace_id: workspaceId,
          },
        )
        setExecutionId(data.execution_id)
        setMode('live')
      } catch (err) {
        console.error('Debug start failed:', err)
      }
    },
    [agentId, agentVersionId, workspaceId, dispatch],
  )

  const handleStop = useCallback(async () => {
    if (!executionId) return
    await apiPost(`/executions/${executionId}/stop`)
  }, [executionId])

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
        <PanelResizeHandle className="w-px bg-border hover:bg-primary-accent/50 transition-colors" />
        <Panel defaultSize={60} minSize={30}>
          <ObservationDetailPanel />
        </Panel>
      </PanelGroup>
    </div>
  )
}

export function DebugPanel(props: DebugPanelProps) {
  return (
    <ObservationViewPrefsProvider>
      <ObservationDataProvider>
        <Suspense fallback={null}>
          <ObservationSelectionProvider>
            <ObservationJsonExpansionProvider>
              <DebugPanelInner {...props} />
            </ObservationJsonExpansionProvider>
          </ObservationSelectionProvider>
        </Suspense>
      </ObservationDataProvider>
    </ObservationViewPrefsProvider>
  )
}

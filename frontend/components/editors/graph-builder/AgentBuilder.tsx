'use client'

import { Loader2 } from 'lucide-react'
import React, { useEffect } from 'react'
import { ReactFlowProvider } from 'reactflow'

import {
  useVersionGraphState,
} from '@/hooks/queries/agentVersions'
import { useAgent } from '@/hooks/queries/agents'
import { useTranslation } from '@/lib/i18n'
import { computeGraphStateHash } from '@/lib/utils/graphStateHash'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

import { useQueryClient } from '@tanstack/react-query'

import { CodeEditorPage } from './CodeEditorPage'
import { GraphBuilderShell } from './GraphBuilderShell'
import { visualDefinitionAdapter } from './services/visualDefinitionAdapter'
import { agentService } from './services/agentService'
import { useGraphStore } from './stores/graphStore'
import { useSaveStore, setSaveStoreQueryClient } from './stores/saveStore'
import { useCodeEditorStore } from './stores/codeEditorStore'
import { useExecutionStore } from './stores/execution/executionStore'
import type { StateField } from './types/graph'

/** Typed shape of graph variables stored alongside canvas state. */
interface BuilderVariables {
  graph_mode?: string
  state_fields?: StateField[]
  code_content?: string
  fallback_node_id?: string
  context?: Record<string, { type?: string; description?: string; value?: unknown }>
}

const isValidUUID = (str: string): boolean => {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  return uuidRegex.test(str)
}

interface AgentBuilderProps {
  agentId: string
  versionId?: string
  workspaceId: string
}

function AgentBuilderInit({
  agentId: agentIdProp,
  versionId: versionIdProp,
  workspaceId: workspaceIdProp,
}: AgentBuilderProps) {
  const { t } = useTranslation()
  const { workspaceId: currentWorkspaceId } = useCurrentWorkspace()
  const queryClient = useQueryClient()
  setSaveStoreQueryClient(queryClient)

  const workspaceId = workspaceIdProp || currentWorkspaceId
  const agentId = agentIdProp && isValidUUID(agentIdProp) ? agentIdProp : null

  const {
    isInitializing,
    rfInstance,
    loadGraph,
    setWorkspaceId,
    setGraphId,
    setGraphName,
  } = useGraphStore()

  const { startAutoSave, stopAutoSave } = useSaveStore()

  const { setCurrentGraphId } = useExecutionStore()

  const { data: agentData } = useAgent(agentId ?? '', workspaceId, {
    enabled: Boolean(agentId && workspaceId),
  })
  const { data: graphStateData, isSuccess: isGraphStateLoaded } = useVersionGraphState(
    agentId ?? undefined,
    versionIdProp,
    workspaceId || undefined,
    { refetchOnMount: 'always', enabled: Boolean(versionIdProp && agentId && workspaceId) },
  )

  // Sync workspaceId into the store
  useEffect(() => {
    if (workspaceId) {
      setWorkspaceId(workspaceId)
    }
  }, [workspaceId, setWorkspaceId])

  // Sync agentId + versionId props into the store
  useEffect(() => {
    useGraphStore.setState({
      agentId: agentId ?? null,
      versionId: versionIdProp ?? null,
    })
  }, [agentId, versionIdProp])

  // Sync currentGraphId in executionStore when agentId changes
  useEffect(() => {
    setCurrentGraphId(agentId || null)
  }, [agentId, setCurrentGraphId])

  // Cleanup execution state on unmount
  useEffect(() => {
    return () => {
      const { currentGraphId } = useExecutionStore.getState()
      if (currentGraphId) {
        useExecutionStore.getState().clearGraphState(currentGraphId)
      }
    }
  }, [])

  const graphId = useGraphStore((state) => state.graphId)
  const graphName = useGraphStore((state) => state.graphName)

  // Auto-save lifecycle
  useEffect(() => {
    if (graphId && graphId === agentId && graphName && !isInitializing) {
      startAutoSave()
    }

    return () => {
      stopAutoSave()
    }
  }, [graphId, graphName, isInitializing, agentId, startAutoSave, stopAutoSave])

  // Handle online event (reconnect save)
  useEffect(() => {
    const handleOnline = () => {
      const { hasPendingChanges, lastSaveError } = useSaveStore.getState()
      if (hasPendingChanges || lastSaveError === 'offline') {
        useSaveStore.setState({ saveRetryCount: 0, lastSaveError: null })
        useSaveStore.getState().autoSave()
      }
    }

    window.addEventListener('online', handleOnline)
    return () => {
      window.removeEventListener('online', handleOnline)
    }
  }, [])

  // Handle beforeunload (beacon save)
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      const { nodes, edges, rfInstance, graphId, versionId, workspaceId } =
        useGraphStore.getState()
      const { hasPendingChanges } = useSaveStore.getState()

      if (!graphId || graphId !== agentId || !isValidUUID(graphId)) {
        return
      }

      if (hasPendingChanges && versionId && workspaceId) {
        try {
          const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }
          visualDefinitionAdapter.sendBeaconSave(graphId, versionId, workspaceId, {
            nodes,
            edges,
            viewport,
          })
        } catch {
          // Silent fail for sendBeacon
        }

        e.preventDefault()
        e.returnValue = ''
        return ''
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [agentId])

  // Use ref to track loaded graphId, avoiding duplicate initialization
  const loadedGraphIdRef = React.useRef<string | null>(null)
  // Track viewport setting timers for cleanup
  const viewportTimersRef = React.useRef<NodeJS.Timeout[]>([])

  // Load graph when agentId changes and graph state is loaded from React Query
  useEffect(() => {
    if (!agentId) {
      loadGraph()
      return
    }

    if (loadedGraphIdRef.current !== agentId) {
      useGraphStore.setState({ isInitializing: true, rfInstance: null })

      if (!isGraphStateLoaded || !graphStateData) {
        return
      }
    }

    if (!isGraphStateLoaded || !graphStateData) {
      useGraphStore.setState({ isInitializing: true })
      return
    }

    if (loadedGraphIdRef.current === agentId && !useGraphStore.getState().isInitializing) {
      return
    }

    const state = graphStateData

    // Code mode: hydrate code editor store instead of canvas
    if (state.definitionKind === 'langgraph_code' && agentId) {
      const loadedVars = (state.variables ?? {}) as BuilderVariables
      const agentName = agentData?.name
      useCodeEditorStore
        .getState()
        .hydrate(agentId, loadedVars.code_content ?? '', agentName ?? '', versionIdProp ?? null, workspaceId || null)
      loadedGraphIdRef.current = agentId
      useGraphStore.setState({ isInitializing: false })
      return
    }

    if (agentId) {
      agentService.setCachedGraphId(agentId)
      setGraphId(agentId)
    }

    if (agentData) {
      if (agentData.name) {
        agentService.setCachedGraphName(agentData.name)
        setGraphName(agentData.name)
      }
      if (agentData.updated_at) {
        const updatedAtTime = new Date(agentData.updated_at).getTime()
        useSaveStore.setState({ lastAutoSaveTime: updatedAtTime })
      }
    }

    const loadedVariables = (state.variables || {}) as BuilderVariables
    const loadedStateFields = (() => {
      const sf = loadedVariables.state_fields || []
      if (sf.length > 0) return sf
      const ctx = loadedVariables.context || {}
      if (Object.keys(ctx).length === 0) return []
      return Object.entries(ctx).map(([key, v]) => ({
        name: key,
        type: (v?.type === 'number'
          ? 'int'
          : v?.type === 'boolean'
            ? 'bool'
            : v?.type || 'string') as StateField['type'],
        description: v?.description || '',
        defaultValue: v?.value,
      }))
    })()
    const loadedFallbackNodeId = loadedVariables.fallback_node_id ?? null

    const initialHash = computeGraphStateHash(
      state.nodes || [],
      state.edges || [],
      loadedStateFields,
      loadedFallbackNodeId,
    )

    useGraphStore.setState({
      nodes: state.nodes || [],
      edges: state.edges || [],
      graphStateFields: loadedStateFields,
      fallbackNodeId: loadedFallbackNodeId,
      past: [],
      future: [],
      selectedNodeId: null,
      isInitializing: false,
    })

    useSaveStore.setState({
      lastSavedStateHash: initialHash,
      saveRetryCount: 0,
      lastSaveError: null,
    })

    loadedGraphIdRef.current = agentId

    let retryCount = 0
    const maxRetries = 40
    const setViewportWhenReady = () => {
      const currentRfInstance = useGraphStore.getState().rfInstance
      const currentNodes = useGraphStore.getState().nodes

      if (currentRfInstance && currentNodes.length > 0) {
        const finalTimer = setTimeout(() => {
          if (state.viewport) {
            currentRfInstance.setViewport(state.viewport, { duration: 0 })
          } else {
            currentRfInstance.fitView({ padding: 0.2, duration: 0 })
          }
        }, 150)
        viewportTimersRef.current.push(finalTimer)
      } else if (retryCount < maxRetries) {
        retryCount++
        const retryTimer = setTimeout(setViewportWhenReady, 50)
        viewportTimersRef.current.push(retryTimer)
      }
    }

    setViewportWhenReady()

    return () => {
      viewportTimersRef.current.forEach((timer) => {
        if (timer) clearTimeout(timer)
      })
      viewportTimersRef.current = []
    }
  }, [agentId, isGraphStateLoaded, graphStateData, agentData, loadGraph, setGraphId, setGraphName])

  // Code mode: render CodeEditorPage instead of canvas
  if (graphStateData?.definitionKind === 'langgraph_code' && agentId && !isInitializing) {
    return <CodeEditorPage graphId={agentId} workspaceId={workspaceId} />
  }

  // Loading overlay
  if (isInitializing) {
    return (
      <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-[var(--bg)] backdrop-blur-sm">
        <Loader2 size={40} className="mb-3 animate-spin text-[var(--brand-500)]" />
        <p className="font-medium text-[var(--text-muted)]">{t('workspace.loadingWorkspace')}</p>
      </div>
    )
  }

  return (
    <GraphBuilderShell
      agentId={agentIdProp}
    />
  )
}

export default function AgentBuilder(props: AgentBuilderProps) {
  return (
    <ReactFlowProvider>
      <AgentBuilderInit {...props} />
    </ReactFlowProvider>
  )
}

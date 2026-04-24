'use client'

import { Loader2, AlertTriangle, FilePlus } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useEffect, useState } from 'react'
import { ReactFlowProvider } from 'reactflow'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useVersionGraphState } from '@/hooks/queries/agentVersions'
import { useAgent } from '@/hooks/queries/agents'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { computeGraphStateHash } from '@/lib/utils/graphStateHash'
import { useWorkspaces } from '@/hooks/queries/workspaces'

import { BuilderCanvas } from './components/BuilderCanvas'
import { BuilderSidebarTabs } from './components/BuilderSidebarTabs'
import { BuilderToolbar } from './components/BuilderToolbar'
import { ExecutionPanelNew as ExecutionPanel } from './components/execution/ExecutionPanelNew'
import { RunInputModal } from './components/RunInputModal'
import { CodeEditorPage } from './CodeEditorPage'
import { useCodeEditorStore } from './stores/codeEditorStore'
import { ErrorBoundary } from './error-boundary'
import { agentService } from './services/agentService'
import { graphDataAdapter } from './services/graphDataAdapter'
import { useBuilderStore } from './stores/builderStore'
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

interface AgentBuilderContentProps {
  workspaceIdProp?: string
  agentIdProp?: string
  versionIdProp?: string
}

const AgentBuilderContent = ({ workspaceIdProp, agentIdProp, versionIdProp }: AgentBuilderContentProps) => {
  const { t } = useTranslation()
  const params = useParams()
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')

  // Use prop if provided, otherwise try URL param, otherwise fall back to personal workspace
  const workspaceId = workspaceIdProp || (params.workspaceId as string) || personalWorkspace?.id || ''
  const rawAgentId = agentIdProp || (params.agentId as string | undefined)
  const agentId = rawAgentId && isValidUUID(rawAgentId) ? rawAgentId : null

  const {
    isInitializing,
    rfInstance,
    nodes,
    loadGraph,
    exportGraph,
    importGraph,
    setWorkspaceId,
    setGraphId,
    setGraphName,
    startAutoSave,
    stopAutoSave,
  } = useBuilderStore()

  const { showPanel: showExecutionPanel, startExecution, setCurrentGraphId } = useExecutionStore()

  const { data: agentData } = useAgent(agentId ?? '', workspaceId, { enabled: Boolean(agentId && workspaceId) })
  const { data: graphStateData, isSuccess: isGraphStateLoaded } = useVersionGraphState(
    agentId ?? undefined,
    versionIdProp,
    workspaceId || undefined,
    { refetchOnMount: 'always', enabled: Boolean(versionIdProp && agentId && workspaceId) },
  )

  const { toast } = useToast()
  const [showOverwriteConfirm, setShowOverwriteConfirm] = useState(false)
  const [showNewConfirm, setShowNewConfirm] = useState(false)
  const [pendingGraph, setPendingGraph] = useState<
    { type: 'import'; file: File } | null
  >(null)
  const [isRunModalOpen, setIsRunModalOpen] = useState(false)
  const [runInput, setRunInput] = useState('')

  // Set workspaceId and agentId in the store
  useEffect(() => {
    if (workspaceId) {
      setWorkspaceId(workspaceId)
    }
  }, [workspaceId, setWorkspaceId])

  // Sync agentId + versionId props into the store so downstream consumers can read them
  useEffect(() => {
    useBuilderStore.setState({
      agentId: agentId ?? null,
      versionId: versionIdProp ?? null,
    })
  }, [agentId, versionIdProp])

  // Sync currentGraphId in executionStore when agentId changes
  // This ensures each graph has its own execution state
  useEffect(() => {
    setCurrentGraphId(agentId || null)
  }, [agentId, setCurrentGraphId])

  // Cleanup execution state and WebSocket when the component unmounts
  useEffect(() => {
    return () => {
      const { currentGraphId } = useExecutionStore.getState()
      if (currentGraphId) {
        useExecutionStore.getState().clearGraphState(currentGraphId)
      }
    }
  }, [])

  const graphId = useBuilderStore((state) => state.graphId)
  const graphName = useBuilderStore((state) => state.graphName)

  useEffect(() => {
    if (graphId && graphId === agentId && graphName && !isInitializing) {
      startAutoSave()
    }

    return () => {
      stopAutoSave()
    }
  }, [graphId, graphName, isInitializing, agentId, startAutoSave, stopAutoSave])

  useEffect(() => {
    const handleOnline = () => {
      const { hasPendingChanges, lastSaveError } = useBuilderStore.getState()
      if (hasPendingChanges || lastSaveError === 'offline') {
        useBuilderStore.setState({ saveRetryCount: 0, lastSaveError: null })
        useBuilderStore.getState().autoSave()
      }
    }

    window.addEventListener('online', handleOnline)
    return () => {
      window.removeEventListener('online', handleOnline)
    }
  }, [])

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      const { hasPendingChanges, nodes, edges, rfInstance, graphId, versionId, workspaceId } = useBuilderStore.getState()

      if (!graphId || graphId !== agentId || !isValidUUID(graphId)) {
        return
      }

      if (hasPendingChanges && versionId && workspaceId) {
        try {
          const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }
          graphDataAdapter.sendBeaconSave(graphId, versionId, workspaceId, {
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
    // Wait for necessary data to load
    if (!agentId) {
      loadGraph()
      return
    }

    // When switching to a different agent
    if (loadedGraphIdRef.current !== agentId) {
      // Important: DO NOT clear the canvas yet.
      // Wait until we have the new data to avoid triggering auto-save on an empty state.
      useBuilderStore.setState({ isInitializing: true })
      // Clear stale rfInstance so setViewportWhenReady waits for the new ReactFlow instance
      useBuilderStore.setState({ rfInstance: null })

      // If we don't have data yet, we must stop here and wait for the next run
      if (!isGraphStateLoaded || !graphStateData) {
        return
      }
    }

    // Wait for graph state data to load
    if (!isGraphStateLoaded || !graphStateData) {
      useBuilderStore.setState({ isInitializing: true })
      return
    }

    // Avoid duplicate initialization for the same graphId
    if (loadedGraphIdRef.current === agentId && !useBuilderStore.getState().isInitializing) {
      return
    }

    // Use React Query cached state data
    const state = graphStateData

    // Code mode: hydrate code editor store instead of canvas
    const loadedVars = (state.variables ?? {}) as BuilderVariables
    const graphMode = loadedVars.graph_mode
    if (graphMode === 'code' && agentId) {
      const agentName = agentData?.name
      useCodeEditorStore
        .getState()
        .hydrate(agentId, loadedVars.code_content ?? '', agentName ?? '', versionIdProp ?? null, workspaceId || null)
      loadedGraphIdRef.current = agentId
      useBuilderStore.setState({ isInitializing: false })
      return
    }

    // CRITICAL: Ensure we are applying data for the CORRECT agentId
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
        useBuilderStore.setState({ lastAutoSaveTime: updatedAtTime })
      }
    }

    // Parse stateFields and fallbackNodeId from the loaded graph state
    // so the hash is computed with the correct values for THIS graph,
    // not stale values from the previous graph still in the store.
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

    // Calculate hash of initial state (same 4 params as SaveManager for consistency)
    const initialHash = computeGraphStateHash(
      state.nodes || [],
      state.edges || [],
      loadedStateFields,
      loadedFallbackNodeId,
    )

    // Apply multiple state changes in one batch to ensure consistency
    useBuilderStore.setState({
      nodes: state.nodes || [],
      edges: state.edges || [],
      graphStateFields: loadedStateFields,
      fallbackNodeId: loadedFallbackNodeId,
      past: [],
      future: [],
      selectedNodeId: null,
      lastSavedStateHash: initialHash,
      saveRetryCount: 0,
      lastSaveError: null,
      isInitializing: false, // FINALLY mark as non-initializing
    })

    // Now we are officially initialized for this agentId
    loadedGraphIdRef.current = agentId

    // Wait for ReactFlow instance to be ready
    let retryCount = 0
    const maxRetries = 40
    const setViewportWhenReady = () => {
      const currentRfInstance = useBuilderStore.getState().rfInstance
      const currentNodes = useBuilderStore.getState().nodes

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


  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Check if current canvas has nodes
    if (nodes.length > 0) {
      // Show confirmation dialog
      setPendingGraph({ type: 'import', file })
      setShowOverwriteConfirm(true)
      // Reset file input
      e.target.value = ''
      return
    }

    // Import directly if canvas is empty
    try {
      await importGraph(file)
      toast({
        title: t('workspace.graphImported'),
        description: t('workspace.graphImportedSuccess', { name: file.name }),
      })

      // Fit view after import
      setTimeout(() => {
        rfInstance?.fitView({ padding: 0.2 })
      }, 100)
    } catch (error: unknown) {
      console.error('Failed to import graph:', error)
      toast({
        variant: 'destructive',
        title: t('workspace.importFailed'),
        description: error instanceof Error ? error.message : t('workspace.importFailedMessage'),
      })
    }

    // Reset file input
    e.target.value = ''
  }

  const handleConfirmOverwrite = async () => {
    if (!pendingGraph) {
      setShowOverwriteConfirm(false)
      return
    }

    try {
      await importGraph(pendingGraph.file)
      toast({
        title: t('workspace.graphImported'),
        description: t('workspace.graphImportedSuccess', { name: pendingGraph.file.name }),
      })

      setTimeout(() => {
        rfInstance?.fitView({ padding: 0.2 })
      }, 100)
    } catch (error: unknown) {
      console.error('Failed to import graph:', error)
      toast({
        variant: 'destructive',
        title: t('workspace.importFailed'),
        description: error instanceof Error ? error.message : t('workspace.importFailedMessage'),
      })
    }

    setPendingGraph(null)
    setShowOverwriteConfirm(false)
  }

  const handleCancelOverwrite = () => {
    setPendingGraph(null)
    setShowOverwriteConfirm(false)
  }

  const createNewGraph = () => {
    agentService.clearCachedGraphId()
    agentService.clearCachedGraphName()
    setGraphId(null)
    setGraphName(null)
    // Clear executionStore currentGraphId for new graph
    setCurrentGraphId(null)

    useBuilderStore.setState({
      nodes: [],
      edges: [],
      past: [],
      future: [],
      selectedNodeId: null,
      lastSavedStateHash: null,
      saveRetryCount: 0,
      lastSaveError: null,
      lastAutoSaveTime: null,
    })

    // Reset viewport
    setTimeout(() => {
      rfInstance?.setViewport({ x: 0, y: 0, zoom: 1 })
    }, 100)

    toast({
      title: t('workspace.newGraphCreated'),
      description: t('workspace.newGraphCreatedDescription'),
    })
  }

  const handleConfirmNew = () => {
    setShowNewConfirm(false)
    createNewGraph()
  }

  const handleRunClick = () => {
    setIsRunModalOpen(true)
  }

  const handleStartExecution = () => {
    if (!runInput.trim()) return
    setIsRunModalOpen(false)
    startExecution(runInput)
    setRunInput('')
  }

  // Code mode: render CodeEditorPage instead of canvas
  const graphMode = (graphStateData?.variables as BuilderVariables | undefined)?.graph_mode
  if (graphMode === 'code' && agentId && !isInitializing) {
    return <CodeEditorPage graphId={agentId} workspaceId={workspaceId} />
  }

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">

      <AlertDialog open={showOverwriteConfirm} onOpenChange={setShowOverwriteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <div className="mb-2 flex items-center gap-1 text-[var(--status-warning)]">
              <AlertTriangle size={20} />
              <AlertDialogTitle>{t('workspace.overwriteCanvas')}</AlertDialogTitle>
            </div>
            <AlertDialogDescription>
              {t('workspace.importOverwriteWarning')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelOverwrite}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmOverwrite}
              className="bg-primary hover:bg-primary/90"
            >
              {t('workspace.import')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showNewConfirm} onOpenChange={setShowNewConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <div className="mb-2 flex items-center gap-1 text-[var(--status-success)]">
              <FilePlus size={20} />
              <AlertDialogTitle>{t('workspace.createNewGraph')}</AlertDialogTitle>
            </div>
            <AlertDialogDescription>{t('workspace.newGraphWarning')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmNew}
              className="bg-[var(--status-success)] hover:bg-[var(--status-success-hover)]"
            >
              {t('workspace.createNew')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {isInitializing && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-[var(--bg)] backdrop-blur-sm">
          <Loader2 size={40} className="mb-3 animate-spin text-[var(--brand-500)]" />
          <p className="font-medium text-[var(--text-muted)]">
            {t('workspace.loadingWorkspace')}
          </p>
        </div>
      )}

      {/* Main Content Area - Canvas takes full space, panels overlay on top */}
      <div className="relative min-h-0 flex-1">
        <ErrorBoundary>
          <BuilderCanvas key={agentId || 'empty'} />
        </ErrorBoundary>
      </div>

      {/* RIGHT: Panel - Absolute Position within the relative container (combines Toolbar and Sidebar) */}
      <aside className="absolute inset-y-0 right-0 z-20 flex w-[320px] flex-col overflow-hidden border-l border-[var(--border-muted)] bg-[var(--surface-2)]">
        {/* Header with Toolbar */}
        <div className="flex-shrink-0 border-b border-[var(--border)]">
          <BuilderToolbar
            onImport={handleImport}
            onExport={exportGraph}
            onRunClick={handleRunClick}
            agentId={agentId || ''}
            nodesCount={nodes.length}
          />
        </div>

        {/* Sidebar Content with Tabs (Copilot and Toolbox) */}
        <div className="min-h-0 flex-1 overflow-hidden">
          <BuilderSidebarTabs />
        </div>
      </aside>

      {/* Run Input Modal - Below Toolbar */}
      <RunInputModal
        isOpen={isRunModalOpen}
        input={runInput}
        onInputChange={setRunInput}
        onStart={handleStartExecution}
        onClose={() => setIsRunModalOpen(false)}
      />

      {/* Execution Panel - Bottom Dock */}
      {showExecutionPanel && <ExecutionPanel />}
    </div>
  )
}

interface AgentBuilderProps {
  workspaceId?: string
  agentId?: string
  versionId?: string
}

const AgentBuilder = ({ workspaceId, agentId: agentIdProp, versionId }: AgentBuilderProps = {}) => (
  <ReactFlowProvider>
    <AgentBuilderContent workspaceIdProp={workspaceId} agentIdProp={agentIdProp} versionIdProp={versionId} />
  </ReactFlowProvider>
)

export default AgentBuilder

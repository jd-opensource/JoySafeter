'use client'

import { useQueryClient } from '@tanstack/react-query'
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
import { useGraphs, useDeploymentStatus, useGraphState, graphKeys } from '@/hooks/queries/graphs'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { computeGraphStateHash } from '@/utils/graphStateHash'

import { BuilderCanvas } from './components/BuilderCanvas'
import { BuilderSidebarTabs } from './components/BuilderSidebarTabs'
import { BuilderToolbar } from './components/BuilderToolbar'
import { ExecutionPanel } from './components/ExecutionPanel'
import { LoadModal } from './components/LoadModal'
import { RunInputModal } from './components/RunInputModal'
import { agentService, AgentGraph } from './services/agentService'
import { useBuilderStore } from './stores/builderStore'
import { useExecutionStore } from './stores/executionStore'



const AgentBuilderContent = () => {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const agentId = params.agentId as string

  const {
    isInitializing,
    isSaving,
    past,
    future,
    rfInstance,
    nodes,
    loadGraph,
    saveGraph,
    undo,
    redo,
    exportGraph,
    importGraph,
    setWorkspaceId,
    setGraphId,
    setGraphName,
    startAutoSave,
    stopAutoSave,
    setDeployedAt,
    hasPendingChanges,
  } = useBuilderStore()

  const { showPanel: showExecutionPanel, startExecution, setCurrentGraphId } = useExecutionStore()

  const queryClient = useQueryClient()

  // Use React Query hooks to fetch data (automatic caching and deduplication)
  // These hooks automatically share cache with other components like sidebar
  const { data: graphsData, isSuccess: isGraphsLoaded } = useGraphs(workspaceId)
  const { data: deploymentStatus } = useDeploymentStatus(agentId)

  // Use React Query to fetch graph state uniformly, avoiding duplicate requests
  // refetchOnMount: 'always' ensures latest data is fetched when switching graphs
  const { data: graphStateData, isSuccess: isGraphStateLoaded } = useGraphState(agentId, {
    refetchOnMount: 'always'
  })

  const { toast } = useToast()
  const [showLoadModal, setShowLoadModal] = useState(false)
  const [showOverwriteConfirm, setShowOverwriteConfirm] = useState(false)
  const [showNewConfirm, setShowNewConfirm] = useState(false)
  const [pendingGraph, setPendingGraph] = useState<AgentGraph | { type: 'import'; file: File } | null>(null)
  const [isLoadingGraph, setIsLoadingGraph] = useState(false)
  const [isRunModalOpen, setIsRunModalOpen] = useState(false)
  const [runInput, setRunInput] = useState('')

  // Set workspaceId and agentId in the store
  useEffect(() => {
    if (workspaceId) {
      setWorkspaceId(workspaceId)
    }
  }, [workspaceId, setWorkspaceId])

  // Sync currentGraphId in executionStore when agentId changes
  // This ensures each graph has its own execution state
  useEffect(() => {
    setCurrentGraphId(agentId || null)
  }, [agentId, setCurrentGraphId])

  const graphId = useBuilderStore((state) => state.graphId)
  const graphName = useBuilderStore((state) => state.graphName)

  useEffect(() => {
    if (graphId && graphName && !isInitializing) {
      startAutoSave()
    }

    return () => {
      stopAutoSave()
    }
  }, [graphId, graphName, isInitializing, startAutoSave, stopAutoSave])

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
      const { hasPendingChanges, autoSaveDebounceTimer, nodes, edges, rfInstance, graphId } = useBuilderStore.getState()

      if (hasPendingChanges || autoSaveDebounceTimer) {
        if (autoSaveDebounceTimer) {
          clearTimeout(autoSaveDebounceTimer)
        }

        if (graphId) {
          try {
            const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }
            const payload = JSON.stringify({
              nodes,
              edges,
              viewport,
            })

            const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL || ''
            const url = `${apiBaseUrl}/v1/graphs/${graphId}/state`
            const blob = new Blob([payload], { type: 'application/json' })
            navigator.sendBeacon(url, blob)
          } catch (error) {
            // Silent fail for sendBeacon
          }

          e.preventDefault()
          e.returnValue = ''
          return ''
        }
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [])

  // Use ref to track loaded graphId, avoiding duplicate initialization
  const loadedGraphIdRef = React.useRef<string | null>(null)
  // Track viewport setting timers for cleanup
  const viewportTimersRef = React.useRef<NodeJS.Timeout[]>([])

  // Load graph when agentId changes and graph state is loaded from React Query
  // Key optimization: Use React Query cached data instead of directly calling agentService.loadGraphState
  useEffect(() => {
    // Wait for necessary data to load
    if (!agentId) {
      loadGraph()
      return
    }

    // Wait for graph state data to load
    if (!isGraphStateLoaded || !graphStateData) {
      // Data is still loading, set initialization state
      useBuilderStore.setState({ isInitializing: true })
      return
    }

    // Avoid duplicate initialization for the same graphId
    if (loadedGraphIdRef.current === agentId) {
      return
    }
    loadedGraphIdRef.current = agentId

    // Use React Query cached state data
    const state = graphStateData

    agentService.setCachedGraphId(agentId)
    setGraphId(agentId)

    // Use React Query cached graphs data to get name and other info
    const currentGraph = graphsData?.find(g => g.id === agentId)
    if (currentGraph) {
      if (currentGraph.name) {
        agentService.setCachedGraphName(currentGraph.name)
        setGraphName(currentGraph.name)
      }
      if (currentGraph.updatedAt) {
        const updatedAtTime = new Date(currentGraph.updatedAt).getTime()
        useBuilderStore.setState({ lastAutoSaveTime: updatedAtTime })
      }
    } else {
      // If graphsData is not loaded yet or graph not found, set a default name
      // This ensures save operations can proceed even if graphName is not yet available
      const defaultName = '(not set)'
      if (!useBuilderStore.getState().graphName) {
        agentService.setCachedGraphName(defaultName)
        setGraphName(defaultName)
      }
    }

    // Calculate hash of initial state to determine if there are changes during auto-save
    // This is key to solving the "POST immediately after page load" issue
    const initialHash = computeGraphStateHash(state.nodes || [], state.edges || [])

    useBuilderStore.setState({
      nodes: state.nodes || [],
      edges: state.edges || [],
      past: [],
      future: [],
      selectedNodeId: null,
      isInitializing: false,
      hasPendingChanges: false,
      lastSavedStateHash: initialHash, // 设置初始 hash，避免立即触发保存
      saveRetryCount: 0,
      lastSaveError: null,
    })

    // 同步 SaveManager 的 hash，确保在启动自动保存前 hash 已同步
    // 使用 setTimeout 确保状态更新已完成
    const syncTimer = setTimeout(() => {
      const { syncLastSavedHash } = useBuilderStore.getState()
      syncLastSavedHash()
    }, 0)
    viewportTimersRef.current.push(syncTimer)

    // Wait for ReactFlow instance to be ready and nodes to be rendered before setting viewport
    // This ensures viewport is set correctly whether it's a new creation or a refresh
    let retryCount = 0
    const maxRetries = 40 // Maximum 2 seconds (40 * 50ms) to wait for nodes to render
    const setViewportWhenReady = () => {
      const currentRfInstance = useBuilderStore.getState().rfInstance
      const currentNodes = useBuilderStore.getState().nodes

      // Check if ReactFlow instance is ready and nodes are loaded
      if (currentRfInstance && currentNodes.length > 0) {
        // Wait a bit more for nodes to be fully rendered in the DOM
        const finalTimer = setTimeout(() => {
          if (state.viewport) {
            currentRfInstance.setViewport(state.viewport, { duration: 0 })
          } else {
            // If no viewport, fit view to show all nodes
            currentRfInstance.fitView({ padding: 0.2, duration: 0 })
          }
        }, 150)
        viewportTimersRef.current.push(finalTimer)
      } else if (retryCount < maxRetries) {
        // ReactFlow instance or nodes not ready yet, retry after a short delay
        retryCount++
        const retryTimer = setTimeout(setViewportWhenReady, 50)
        viewportTimersRef.current.push(retryTimer)
      }
    }

    // Start trying to set viewport
    setViewportWhenReady()

    // Cleanup function to clear all timers
    return () => {
      viewportTimersRef.current.forEach(timer => {
        if (timer) {
          clearTimeout(timer)
        }
      })
      viewportTimersRef.current = []
    }
  }, [agentId, isGraphStateLoaded, graphStateData, graphsData, loadGraph, setGraphId, setGraphName])

  // Reset loadedGraphIdRef when agentId changes
  useEffect(() => {
    if (agentId !== loadedGraphIdRef.current) {
      loadedGraphIdRef.current = null
    }
  }, [agentId])

  // Sync deployment status from React Query to builderStore
  // Deployment status is fetched via useDeploymentStatus hook, automatically sharing cache with other components
  useEffect(() => {
    if (deploymentStatus) {
      if (deploymentStatus.isDeployed && deploymentStatus.deployedAt) {
        setDeployedAt(deploymentStatus.deployedAt)
      } else {
        setDeployedAt(null)
      }
    }
  }, [deploymentStatus, setDeployedAt])

  const applyLoadedGraph = async (graph: AgentGraph) => {
    setIsLoadingGraph(true)
    try {
      agentService.setCachedGraphId(graph.id)
      setGraphId(graph.id)
      // Sync executionStore currentGraphId when loading a different graph
      setCurrentGraphId(graph.id)
      if (graph.name) {
        agentService.setCachedGraphName(graph.name)
        setGraphName(graph.name)
      } else {
        // Set default name if graph.name is not available
        const defaultName = '(not set)'
        agentService.setCachedGraphName(defaultName)
        setGraphName(defaultName)
      }

      // Use React Query to fetch state, invalidate cache first to ensure latest data
      await queryClient.invalidateQueries({ queryKey: graphKeys.state(graph.id) })
      const stateResult = await queryClient.fetchQuery({
        queryKey: graphKeys.state(graph.id),
        queryFn: async () => {
          const response = await agentService.loadGraphState(graph.id)
          return response
        },
      })
      const state = stateResult || { nodes: [], edges: [] }

      if (graph.updatedAt) {
        const updatedAtTime = new Date(graph.updatedAt).getTime()
        useBuilderStore.setState({ lastAutoSaveTime: updatedAtTime })
      }

      // Calculate hash of initial state
      const initialHash = computeGraphStateHash(state.nodes || [], state.edges || [])

      useBuilderStore.setState({
        nodes: state.nodes || [],
        edges: state.edges || [],
        past: [],
        future: [],
        selectedNodeId: null,
        hasPendingChanges: false,
        lastSavedStateHash: initialHash, // 设置初始 hash
        saveRetryCount: 0,
        lastSaveError: null,
      })

      // 同步 SaveManager 的 hash，确保在启动自动保存前 hash 已同步
      // 使用 setTimeout 确保状态更新已完成
      setTimeout(() => {
        const { syncLastSavedHash } = useBuilderStore.getState()
        syncLastSavedHash()
      }, 0)

      if (state.viewport && rfInstance) {
        rfInstance.setViewport(state.viewport)
      } else {
        setTimeout(() => {
          rfInstance?.fitView({ padding: 0.2 })
        }, 100)
      }

      // Reset loadedGraphIdRef to allow reloading
      loadedGraphIdRef.current = graph.id

      toast({
        title: t('workspace.graphLoaded'),
        description: t('workspace.graphLoadedSuccess', { name: graph.name }),
      })
    } catch (error) {
      console.error('Failed to load graph state:', error)
      toast({
        variant: 'destructive',
        title: t('common.error'),
        description: t('workspace.graphLoadFailed'),
      })
    } finally {
      setIsLoadingGraph(false)
    }
  }

  const handleLoadAttempt = (graph: AgentGraph) => {
    setShowLoadModal(false)

    // Check if the current canvas is empty
    if (nodes.length > 0) {
      setPendingGraph(graph)
      setShowOverwriteConfirm(true)
    } else {
      applyLoadedGraph(graph)
    }
  }

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
    } catch (error: any) {
      console.error('Failed to import graph:', error)
      toast({
        variant: 'destructive',
        title: t('workspace.importFailed'),
        description: error?.message || t('workspace.importFailedMessage'),
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

    // Handle import case
    if ('type' in pendingGraph && pendingGraph.type === 'import' && pendingGraph.file) {
      try {
        await importGraph(pendingGraph.file)
        toast({
          title: t('workspace.graphImported'),
          description: t('workspace.graphImportedSuccess', { name: pendingGraph.file.name }),
        })

        // Fit view after import
        setTimeout(() => {
          rfInstance?.fitView({ padding: 0.2 })
        }, 100)
      } catch (error: any) {
        console.error('Failed to import graph:', error)
        toast({
          variant: 'destructive',
          title: t('workspace.importFailed'),
          description: error?.message || t('workspace.importFailedMessage'),
        })
      }
    } else {
      // Handle load case (existing logic)
      await applyLoadedGraph(pendingGraph as AgentGraph)
    }

    setPendingGraph(null)
    setShowOverwriteConfirm(false)
  }

  const handleCancelOverwrite = () => {
    const wasImport = pendingGraph && 'type' in pendingGraph && pendingGraph.type === 'import'
    setPendingGraph(null)
    setShowOverwriteConfirm(false)
    // Only reopen load modal if it was a load operation, not an import
    if (!wasImport) {
      setShowLoadModal(true)
    }
  }

  const handleNewGraph = () => {
    // If canvas has nodes, show confirmation dialog
    if (nodes.length > 0) {
      setShowNewConfirm(true)
    } else {
      // Canvas is empty, just reset
      createNewGraph()
    }
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
      hasPendingChanges: false,
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

  return (
    <div className="w-full h-full flex flex-col bg-gray-50 text-gray-900 relative overflow-hidden">
      {showLoadModal && (
        <LoadModal onClose={() => setShowLoadModal(false)} onLoad={handleLoadAttempt} />
      )}

      <AlertDialog open={showOverwriteConfirm} onOpenChange={setShowOverwriteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <div className="flex items-center gap-1 text-amber-600 mb-2">
              <AlertTriangle size={20} />
              <AlertDialogTitle>{t('workspace.overwriteCanvas')}</AlertDialogTitle>
            </div>
            <AlertDialogDescription>
              {pendingGraph && 'type' in pendingGraph && pendingGraph.type === 'import'
                ? t('workspace.importOverwriteWarning')
                : t('workspace.loadOverwriteWarning', {
                    name: pendingGraph && 'name' in pendingGraph ? pendingGraph.name : '',
                  })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelOverwrite}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmOverwrite} className="bg-blue-600 hover:bg-blue-700">
              {pendingGraph && 'type' in pendingGraph && pendingGraph.type === 'import'
                ? t('workspace.import')
                : t('workspace.overwriteAndLoad')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showNewConfirm} onOpenChange={setShowNewConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <div className="flex items-center gap-1 text-green-600 mb-2">
              <FilePlus size={20} />
              <AlertDialogTitle>{t('workspace.createNewGraph')}</AlertDialogTitle>
            </div>
            <AlertDialogDescription>
              {t('workspace.newGraphWarning')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmNew} className="bg-green-600 hover:bg-green-700">
              {t('workspace.createNew')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {(isInitializing || isLoadingGraph) && (
        <div className="absolute inset-0 z-[60] bg-gray-50/80 backdrop-blur-sm flex flex-col items-center justify-center">
          <Loader2 size={40} className="text-blue-500 animate-spin mb-3" />
          <p className="text-gray-500 font-medium">
            {isLoadingGraph ? t('workspace.loadingGraph') : t('workspace.loadingWorkspace')}
          </p>
        </div>
      )}

      {/* Main Content Area - Canvas takes full space, panels overlay on top */}
      <div className="flex-1 min-h-0 relative">
        <BuilderCanvas />
      </div>

      {/* RIGHT: Panel - Fixed Position (combines Toolbar and Sidebar) */}
      <aside className="fixed inset-y-0 right-0 z-20 w-[320px] bg-white border-l border-gray-200 overflow-hidden flex flex-col">
        {/* Header with Toolbar */}
        <div className="flex-shrink-0 border-b border-gray-200">
          <BuilderToolbar
            onImport={handleImport}
            onExport={exportGraph}
            onRunClick={handleRunClick}
            agentId={agentId}
            nodesCount={nodes.length}
          />
        </div>

        {/* Sidebar Content with Tabs (Copilot and Toolbox) */}
        <div className="flex-1 min-h-0 overflow-hidden">
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

const AgentBuilder = () => (
  <ReactFlowProvider>
    <AgentBuilderContent />
  </ReactFlowProvider>
)

export default AgentBuilder

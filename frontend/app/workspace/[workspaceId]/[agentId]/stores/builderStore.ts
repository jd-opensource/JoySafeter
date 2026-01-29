'use client'

/**
 * Builder Store - Graph/Canvas State Management
 *
 * This store manages only the graph building functionality:
 * - Nodes and edges
 * - History (undo/redo)
 * - Graph persistence (load/save/import/export)
 *
 * Execution state is managed separately in executionStore.ts
 *
 * Save Management:
 * - All save operations are managed by SaveManager (see utils/saveManager.ts)
 * - SaveManager handles: manual saves, auto-saves, and debounced saves
 * - Timer fields (autoSaveTimer, autoSaveDebounceTimer) are kept for backward compatibility
 *   but are actually managed by SaveManager internally
 */

import {
  Connection,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  addEdge,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
  applyNodeChanges,
  applyEdgeChanges,
  ReactFlowInstance,
} from 'reactflow'
import { create } from 'zustand'

import { i18n } from '@/lib/i18n'
import { useSidebarStore } from '@/stores/sidebar/store'
import type { GraphAction } from '@/types/copilot'
import { ActionProcessor } from '@/utils/copilot/actionProcessor'
import { computeGraphStateHash } from '@/utils/graphStateHash'

import type { ContextVariable } from '../components/GraphSettingsPanel'
import { agentService } from '../services/agentService'
import { migrateGraphData, needsMigration } from '../services/dataMigration'
import { nodeRegistry } from '../services/nodeRegistry'
import { EdgeData, RouteRule } from '../types/graph'
import { SaveManager, type GraphState as SaveManagerGraphState } from '../utils/saveManager'

// Track import graph timers to allow cleanup
let importGraphTimeout1: NodeJS.Timeout | null = null
let importGraphTimeout2: NodeJS.Timeout | null = null

interface HistoryState {
  nodes: Node[]
  edges: Edge[]
}

interface ExecutionLog {
  timestamp: number
  nodeId: string
  nodeLabel: string
  message: string
  status: 'info' | 'success' | 'error'
}

interface BuilderState {
  // Canvas State
  nodes: Node[]
  edges: Edge[]
  rfInstance: ReactFlowInstance | null
  selectedNodeId: string | null
  selectedEdgeId: string | null

  // History State
  past: HistoryState[]
  future: HistoryState[]

  // UI State
  isSaving: boolean
  isInitializing: boolean
  showGraphSettings: boolean
  showValidationSummary: boolean

  // Execution State
  isExecuting: boolean
  activeExecutionNodeId: string | null
  executionLogs: ExecutionLog[]

  // Graph Variables State (context variables for condition expressions)
  graphVariables: Record<string, ContextVariable>

  // Auto-save State
  lastAutoSaveTime: number | null
  deployedAt: string | null
  workspaceId: string | null
  graphId: string | null
  graphName: string | null
  autoSaveTimer: NodeJS.Timeout | null // Managed by SaveManager, kept for backward compatibility
  autoSaveDebounceTimer: NodeJS.Timeout | null // Managed by SaveManager, kept for backward compatibility
  lastSavedStateHash: string | null
  hasPendingChanges: boolean
  saveRetryCount: number
  lastSaveError: string | null

  onNodesChange: OnNodesChange
  onEdgesChange: OnEdgesChange
  onConnect: OnConnect
  setRfInstance: (instance: ReactFlowInstance) => void

  // History Actions
  setWorkspaceId: (workspaceId: string) => void
  setGraphId: (graphId: string | null) => void
  setGraphName: (graphName: string | null) => void
  undo: () => void
  redo: () => void
  takeSnapshot: () => void

  // Node Actions
  addNode: (type: string, position: { x: number; y: number }, label?: string, configOverride?: Record<string, unknown>) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  updateNodeLabel: (id: string, label: string) => void
  deleteNode: (id: string) => void
  duplicateNode: (id: string) => void
  selectNode: (id: string | null) => void

  // Edge Actions
  updateEdge: (id: string, data: Partial<EdgeData>) => void
  selectEdge: (id: string | null) => void
  getOutgoingEdges: (nodeId: string) => Edge[]
  syncEdgesWithRouteRules: (nodeId: string, routes: RouteRule[]) => void

  // Graph Persistence
  loadGraph: (graphId?: string) => Promise<void>
  saveGraph: (name: string) => Promise<void>
  autoSave: () => Promise<void>
  triggerAutoSave: () => void
  startAutoSave: () => void
  stopAutoSave: () => void
  setDeployedAt: (deployedAt: string | null) => void
  exportGraph: () => void
  importGraph: (file: File) => Promise<void>
  syncLastSavedHash: () => void

  // Execution Actions
  addLog: (nodeId: string, message: string, status?: 'info' | 'success' | 'error') => void
  startExecution: (input: string) => Promise<void>
  stopExecution: () => void

  // AI Integration
  applyAIChanges: (changes: { nodes?: Node[]; edges?: Edge[] }) => void
  getGraphContext: () => {
    nodes: Node[]
    edges: { source: string; target: string }[]
  }

  // Graph Variables Actions
  updateGraphVariables: (variables: Record<string, ContextVariable>) => void
  setGraphVariable: (key: string, variable: ContextVariable) => void
  deleteGraphVariable: (key: string) => void
  getGraphVariableKeys: () => string[]
  toggleGraphSettings: (show?: boolean) => void
  toggleValidationSummary: (show?: boolean) => void
}

export const useBuilderStore = create<BuilderState>((set, get) => {
  // Create SaveManager instance with access to store state
  const saveManager = new SaveManager(
    (): SaveManagerGraphState => ({
      graphId: get().graphId,
      graphName: get().graphName,
      nodes: get().nodes,
      edges: get().edges,
      viewport: get().rfInstance?.getViewport(),
      graphVariables: get().graphVariables,
      lastSavedStateHash: get().lastSavedStateHash,
    }),
    {
      onSaveSuccess: (hash) => {
        set({
          lastSavedStateHash: hash,
          lastAutoSaveTime: Date.now(),
          hasPendingChanges: false,
          saveRetryCount: 0,
          lastSaveError: null,
        })
      },
      onSaveError: (error) => {
        set({ lastSaveError: error })
      },
    }
  )

  return {
  nodes: [],
  edges: [],
  past: [],
  future: [],
  rfInstance: null,
  selectedNodeId: null,
  selectedEdgeId: null,
  isSaving: false,
  isInitializing: true,
  showGraphSettings: false,
  showValidationSummary: false,
  workspaceId: null,
  graphId: null,
  graphName: null,
  lastAutoSaveTime: null,
  deployedAt: null,
  autoSaveTimer: null,
  autoSaveDebounceTimer: null,
  lastSavedStateHash: null,
  hasPendingChanges: false,
  saveRetryCount: 0,
  lastSaveError: null,
  isExecuting: false,
  activeExecutionNodeId: null,
  executionLogs: [],
  graphVariables: {},

  addLog: (nodeId, message, status: 'info' | 'success' | 'error' = 'info') => {
    const node = get().nodes.find((n) => n.id === nodeId)
    const newLog: ExecutionLog = {
      timestamp: Date.now(),
      nodeId,
      nodeLabel: (node?.data as { label?: string })?.label || 'System',
      message,
      status,
    }
    set((state) => ({ executionLogs: [...state.executionLogs, newLog] }))
  },

  startExecution: async (input: string) => {
    const { nodes, edges } = get()
    if (nodes.length === 0) return

    set({ isExecuting: true, executionLogs: [], activeExecutionNodeId: null })
    get().addLog(
      'system',
      i18n.t('execution.agentStarted', {
        defaultValue: '智能体已启动，输入：{{input}}',
        input
      }).replace('{{input}}', input),
      'info'
    )

    let currentNode: Node | null = nodes[0]
    const visited = new Set()

    while (currentNode && get().isExecuting) {
      set({ activeExecutionNodeId: currentNode.id })
      get().addLog(currentNode.id, i18n.t('workspace.processingLogic'), 'info')

      await new Promise((r) => setTimeout(r, 2000))

      get().addLog(currentNode.id, i18n.t('workspace.stepCompleted'), 'success')
      visited.add(currentNode.id)

      const outEdge = edges.find((e) => e.source === currentNode!.id)
      if (outEdge && !visited.has(outEdge.target)) {
        currentNode = nodes.find((n) => n.id === outEdge.target) || null
        if (currentNode) {
          get().addLog(
            'system',
            i18n.t('workspace.transitioningTo', {
              label: (currentNode.data as { label?: string })?.label,
            }),
            'info'
          )
        }
      } else {
        currentNode = null
      }
    }

    if (get().isExecuting) {
      get().addLog('system', i18n.t('execution.agentCompleted', { defaultValue: '智能体成功完成。' }), 'success')
      set({ isExecuting: false, activeExecutionNodeId: null })
    }
  },

  stopExecution: () => {
    set({ isExecuting: false, activeExecutionNodeId: null })
    get().addLog('system', i18n.t('workspace.executionStopped'), 'error')
  },

  // ========== History Actions ==========

  takeSnapshot: () => {
    const { nodes, edges, past } = get()
    const newPast = [...past, { nodes: [...nodes], edges: [...edges] }].slice(-50)
    set({ past: newPast, future: [] })
  },

  undo: () => {
    const { past, future, nodes, edges } = get()
    if (past.length === 0) return
    const previous = past[past.length - 1]
    set({
      past: past.slice(0, past.length - 1),
      future: [{ nodes, edges }, ...future],
      nodes: previous.nodes,
      edges: previous.edges,
    })
    get().triggerAutoSave()
  },

  redo: () => {
    const { past, future, nodes, edges } = get()
    if (future.length === 0) return
    const next = future[0]
    set({
      past: [...past, { nodes, edges }],
      future: future.slice(1),
      nodes: next.nodes,
      edges: next.edges,
    })
    get().triggerAutoSave()
  },

  // ========== ReactFlow Handlers ==========

  onNodesChange: (changes: NodeChange[]) => {
    if (changes.some((c) => c.type === 'remove')) get().takeSnapshot()
    set({ nodes: applyNodeChanges(changes, get().nodes) })
    get().triggerAutoSave()
  },

  onEdgesChange: (changes: EdgeChange[]) => {
    if (changes.some((c) => c.type === 'remove')) get().takeSnapshot()
    set({ edges: applyEdgeChanges(changes, get().edges) })
    get().triggerAutoSave()
  },

  onConnect: (connection: Connection) => {
    const { edges, nodes } = get()
    const exists = edges.some(
      (e) => e.source === connection.source && e.target === connection.target
    )
    if (exists) {
      return
    }

    // Determine edge type based on source node
    const sourceNode = nodes.find((n) => n.id === connection.source)
    const sourceType = (sourceNode?.data as { type?: string })?.type || ''
    const isConditionalSource = ['router_node', 'condition', 'loop_condition_node'].includes(
      sourceType
    )

    // Initialize edge type
    let edgeType: EdgeData['edge_type'] = isConditionalSource ? 'conditional' : 'normal'

    // Set default edge data with smart route_key suggestion
    let defaultRouteKey: string | undefined = undefined

    if (isConditionalSource) {
      // Try to suggest a route_key based on source node type and existing routes
      if (sourceType === 'router_node') {
        const config = (sourceNode?.data as { config?: { routes?: RouteRule[] } })?.config
        const routes = config?.routes || []
        // Find first route that doesn't have a matching edge yet
        const existingRouteKeys = new Set(
          edges
            .filter((e) => e.source === connection.source)
            .map((e) => ((e.data || {}) as EdgeData).route_key)
            .filter(Boolean)
        )
        const availableRoute = routes.find((r) => !existingRouteKeys.has(r.targetEdgeKey))
        if (availableRoute) {
          defaultRouteKey = availableRoute.targetEdgeKey
        }
      } else if (sourceType === 'condition') {
        // For condition nodes, default to 'true' if no 'true' edge exists, else 'false'
        const hasTrueEdge = edges.some(
          (e) =>
            e.source === connection.source &&
            ((e.data || {}) as EdgeData).route_key === 'true'
        )
        defaultRouteKey = hasTrueEdge ? 'false' : 'true'
      } else if (sourceType === 'loop_condition_node') {
        // For loop nodes, default to 'continue_loop' if no continue edge exists
        const hasContinueEdge = edges.some(
          (e) =>
            e.source === connection.source &&
            ((e.data || {}) as EdgeData).route_key === 'continue_loop'
        )
        defaultRouteKey = hasContinueEdge ? 'exit_loop' : 'continue_loop'

        // If this is a continue_loop edge and source == target, it's a loop back
        if (defaultRouteKey === 'continue_loop' && connection.source === connection.target) {
          edgeType = 'loop_back'
        } else if (defaultRouteKey === 'continue_loop') {
          // Check if target is before source in the graph (loop back scenario)
          const sourceNode = nodes.find((n) => n.id === connection.source)
          const targetNode = nodes.find((n) => n.id === connection.target)
          if (sourceNode && targetNode && targetNode.position.x < sourceNode.position.x) {
            edgeType = 'loop_back'
          }
        }
      }
    }

    const edgeData: EdgeData = {
      edge_type: edgeType,
      route_key: defaultRouteKey,
    }

    // Determine edge style based on type
    let edgeStyle: React.CSSProperties = { stroke: '#cbd5e1', strokeWidth: 1.5 }
    if (edgeType === 'loop_back') {
      edgeStyle = { stroke: '#9333ea', strokeWidth: 2.5, strokeDasharray: '5,5' }
    } else if (edgeType === 'conditional') {
      edgeStyle = { stroke: '#3b82f6', strokeWidth: 2 }
    }

    get().takeSnapshot()
    set({
      edges: addEdge(
        {
          ...connection,
          data: edgeData,
          type: edgeType === 'loop_back' ? 'loop_back' : 'default',
          animated: true,
          style: edgeStyle,
        },
        get().edges
      ),
    })
    get().triggerAutoSave()
  },

  setRfInstance: (instance) => set({ rfInstance: instance }),
  setWorkspaceId: (workspaceId) => set({ workspaceId }),
  setGraphId: (graphId) => {
    set({ graphId })
    // Sync SaveManager hash when graphId changes (e.g., when loading a graph)
    const state = get()
    if (state.lastSavedStateHash) {
      saveManager.setLastSavedHash(state.lastSavedStateHash)
    }
  },
  setGraphName: (graphName) => set({ graphName }),

  // Sync SaveManager's lastSavedHash from state (without changing graphId)
  // Used when lastSavedStateHash is updated after graphId is already set
  syncLastSavedHash: () => {
    const state = get()
    if (state.lastSavedStateHash) {
      saveManager.setLastSavedHash(state.lastSavedStateHash)
    }
  },

  // ========== Node Actions ==========

  addNode: (type, position, label, configOverride) => {
    get().takeSnapshot()
    const def = nodeRegistry.get(type)
    const defaultConfig = { ...def?.defaultConfig }
    // If configuration override is provided, merge into default configuration
    if (configOverride) {
      Object.assign(defaultConfig, configOverride)
    }
    const newNode: Node = {
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      type: 'custom',
      position,
      data: {
        label: label || def?.label || 'New Node',
        type: type,
        config: defaultConfig,
      },
    }
    set({ nodes: [...get().nodes, newNode], selectedNodeId: newNode.id })
    get().triggerAutoSave()
  },

  updateNodeConfig: (id, config) => {
    const node = get().nodes.find((n) => n.id === id)
    const nodeType = (node?.data as { type?: string })?.type || ''

    set({
      nodes: get().nodes.map((n) => {
        if (n.id === id) {
          const nodeData = n.data as { config?: Record<string, unknown> }
          return {
            ...n,
            data: { ...n.data, config: { ...nodeData.config, ...config } },
          }
        }
        return n
      }),
    })

    // Auto-sync edges when router node routes change
    if (nodeType === 'router_node' && config.routes) {
      get().syncEdgesWithRouteRules(id, config.routes as RouteRule[])
    }

    get().triggerAutoSave()
  },

  updateNodeLabel: (id, label) => {
    set({
      nodes: get().nodes.map((node) => {
        if (node.id === id) {
          return { ...node, data: { ...node.data, label } }
        }
        return node
      }),
    })
    get().triggerAutoSave()
  },

  deleteNode: (id) => {
    get().takeSnapshot()
    const { nodes, edges } = get()
    const newNodes = nodes.filter((n) => n.id !== id)
    const newEdges = edges.filter((e) => e.source !== id && e.target !== id)
    set({
      nodes: newNodes,
      edges: newEdges,
      selectedNodeId: null,
    })
    get().triggerAutoSave()
  },

  duplicateNode: (id: string) => {
    get().takeSnapshot()
    const nodeToDuplicate = get().nodes.find((n) => n.id === id)
    if (!nodeToDuplicate) return

    const sidebarState = useSidebarStore.getState()
    const isSidebarCollapsed = sidebarState.isCollapsed
    const sidebarWidth = sidebarState.sidebarWidth || 280
    const offsetX = 200
    const offsetY = 50
    let newX = nodeToDuplicate.position.x + offsetX
    const newY = nodeToDuplicate.position.y + offsetY
    const sidebarLeftBoundary = isSidebarCollapsed ? 190 : 0
    const sidebarRightBoundary = isSidebarCollapsed ? 422 : sidebarWidth

    if (newX < sidebarRightBoundary + 50) {
      newX = sidebarRightBoundary + 50
    }

    const newNode: Node = {
      ...nodeToDuplicate,
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      position: { x: newX, y: newY },
      selected: false,
    }
    set({ nodes: [...get().nodes, newNode], selectedNodeId: newNode.id })
    get().triggerAutoSave()
  },

  selectNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),

  // Edge Actions
  updateEdge: (id, data) => {
    set((state) => ({
      edges: state.edges.map((e) => {
        if (e.id !== id) return e

        const updatedData = { ...(e.data || {}), ...data } as EdgeData
        const edgeType = updatedData.edge_type

        // Update edge type and style based on edge_type
        let edgeTypeForReactFlow: string = 'default'
        let edgeStyle: React.CSSProperties = { ...e.style }

        if (edgeType === 'loop_back') {
          edgeTypeForReactFlow = 'loop_back'
          edgeStyle = {
            ...edgeStyle,
            stroke: '#9333ea', // violet-600
            strokeWidth: 2.5,
            strokeDasharray: '8,4',
          }
        } else if (edgeType === 'conditional') {
          edgeStyle = {
            ...edgeStyle,
            stroke: '#3b82f6', // blue-500
            strokeWidth: 2,
          }
        } else {
          // Normal edge
          edgeStyle = {
            ...edgeStyle,
            stroke: '#cbd5e1', // gray-300
            strokeWidth: 1.5,
          }
        }

        return {
          ...e,
          type: edgeTypeForReactFlow,
          data: updatedData,
          style: edgeStyle,
        }
      }),
      hasPendingChanges: true,
    }))
    get().triggerAutoSave()
  },
  selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),

  getOutgoingEdges: (nodeId) => {
    return get().edges.filter((e) => e.source === nodeId)
  },

  syncEdgesWithRouteRules: (nodeId, routes) => {
    const { edges } = get()
    const outgoingEdges = edges.filter((e) => e.source === nodeId)
    const routeKeys = new Set(routes.map((r) => r.targetEdgeKey).filter(Boolean))

    // Build a map of route_key to route for quick lookup
    const routeMap = new Map(routes.map((r) => [r.targetEdgeKey, r]))

    // Update edges with matching route keys
    const updatedEdges = edges.map((edge) => {
      if (edge.source !== nodeId) return edge

      const edgeData = (edge.data || {}) as EdgeData
      const currentRouteKey = edgeData.route_key

      // If edge has a route_key that's in the routes, keep it (already correct)
      if (currentRouteKey && routeKeys.has(currentRouteKey)) {
        return edge
      }

      // If edge doesn't have a route_key but should (conditional edge), try to match
      if (edgeData.edge_type === 'conditional' && !currentRouteKey) {
        // Try to find a route that doesn't have an edge yet
        // Priority: find first route without a matching edge
        const unmatchedRoute = routes.find((r) => {
          const hasMatchingEdge = outgoingEdges.some(
            (e) => ((e.data || {}) as EdgeData).route_key === r.targetEdgeKey
          )
          return !hasMatchingEdge
        })

        if (unmatchedRoute) {
          return {
            ...edge,
            data: {
              ...edgeData,
              route_key: unmatchedRoute.targetEdgeKey,
            },
          }
        }
      }

      // If route_key is no longer in routes, clear it (but keep the edge)
      if (currentRouteKey && !routeKeys.has(currentRouteKey)) {
        return {
          ...edge,
          data: {
            ...edgeData,
            route_key: undefined,
          },
        }
      }

      return edge
    })

    set({ edges: updatedEdges, hasPendingChanges: true })
    get().triggerAutoSave()
  },

  loadGraph: async (graphId?: string) => {
    set({ isInitializing: true })
    try {
      if (graphId) {
        const state = await agentService.loadGraphState(graphId)
        let { nodes, edges, variables } = state

        // Apply data migration if needed
        if (needsMigration(nodes, edges)) {
          const migrated = migrateGraphData(nodes, edges)
          nodes = migrated.nodes
          edges = migrated.edges
        }

        // Process edges to ensure correct type and style based on edge_type
        const processedEdges = edges.map((edge) => {
          const edgeData = (edge.data || {}) as EdgeData
          const edgeType = edgeData.edge_type

          // Set React Flow edge type and style based on edge_type
          let edgeTypeForReactFlow: string = 'default'
          let edgeStyle: React.CSSProperties = edge.style || {}

          if (edgeType === 'loop_back') {
            edgeTypeForReactFlow = 'loop_back'
            edgeStyle = {
              ...edgeStyle,
              stroke: '#9333ea', // violet-600
              strokeWidth: 2.5,
              strokeDasharray: '8,4',
            }
          } else if (edgeType === 'conditional') {
            edgeStyle = {
              ...edgeStyle,
              stroke: '#3b82f6', // blue-500
              strokeWidth: 2,
            }
          } else {
            // Normal edge - ensure default style
            edgeStyle = {
              ...edgeStyle,
              stroke: edgeStyle.stroke || '#cbd5e1',
              strokeWidth: edgeStyle.strokeWidth || 1.5,
            }
          }

          return {
            ...edge,
            type: edgeTypeForReactFlow,
            style: edgeStyle,
          }
        })

        // Load graph variables from variables.context
        const contextVariables = (variables?.context as Record<string, ContextVariable>) || {}

        set({
          nodes,
          edges: processedEdges,
          graphVariables: contextVariables,
          past: [],
          future: [],
          isInitializing: false
        })
      } else {
        let { nodes, edges } = await agentService.getInitialGraph()

        // Apply data migration if needed
        if (needsMigration(nodes, edges)) {
          const migrated = migrateGraphData(nodes, edges)
          nodes = migrated.nodes
          edges = migrated.edges
        }

        // Process edges to ensure correct type and style based on edge_type
        const processedEdges = edges.map((edge) => {
          const edgeData = (edge.data || {}) as EdgeData
          const edgeType = edgeData.edge_type

          // Set React Flow edge type and style based on edge_type
          let edgeTypeForReactFlow: string = 'default'
          let edgeStyle: React.CSSProperties = edge.style || {}

          if (edgeType === 'loop_back') {
            edgeTypeForReactFlow = 'loop_back'
            edgeStyle = {
              ...edgeStyle,
              stroke: '#9333ea', // violet-600
              strokeWidth: 2.5,
              strokeDasharray: '8,4',
            }
          } else if (edgeType === 'conditional') {
            edgeStyle = {
              ...edgeStyle,
              stroke: '#3b82f6', // blue-500
              strokeWidth: 2,
            }
          } else {
            // Normal edge - ensure default style
            edgeStyle = {
              ...edgeStyle,
              stroke: edgeStyle.stroke || '#cbd5e1',
              strokeWidth: edgeStyle.strokeWidth || 1.5,
            }
          }

          return {
            ...edge,
            type: edgeTypeForReactFlow,
            style: edgeStyle,
          }
        })

        set({ nodes, edges: processedEdges, past: [], future: [], isInitializing: false })
      }
    } catch {
      set({ nodes: [], edges: [], graphVariables: {}, past: [], future: [], isInitializing: false })
    }
  },

  saveGraph: async (name: string) => {
    const { nodes, edges, rfInstance, workspaceId, graphVariables } = get()
    if (!name) return
    set({ isSaving: true })
    try {
      const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }
      const variables = {
        context: graphVariables,
      }
      const { graphId } = await agentService.saveGraph({
        name,
        nodes,
        edges,
        viewport,
        workspaceId,
        variables,
      })
      // Save state using SaveManager
      await saveManager.save('manual', true)
      const currentStateHash = computeGraphStateHash(nodes, edges)
      set({
        graphId,
        graphName: name,
        lastAutoSaveTime: Date.now(),
        lastSavedStateHash: currentStateHash,
        hasPendingChanges: false,
        saveRetryCount: 0,
        lastSaveError: null,
      })
    } finally {
      set({ isSaving: false })
    }
  },

  autoSave: async () => {
    await saveManager.save('auto')
  },

  triggerAutoSave: () => {
    const { graphId } = get()

    if (!graphId) return

    set({ hasPendingChanges: true })
    saveManager.debouncedSave()
  },

  startAutoSave: () => {
    const { lastSavedStateHash } = get()

    // 同步 lastSavedHash 到 SaveManager（如果还未同步）
    // 这确保在启动自动保存前，SaveManager 知道当前状态的 hash
    if (lastSavedStateHash) {
      saveManager.setLastSavedHash(lastSavedStateHash)
    }

    // 立即保存当前状态以建立基线（但会检查 hash，如果匹配则跳过）
    saveManager.save('auto')
  },

  stopAutoSave: () => {
    saveManager.stopAll()
    // Clear timer references in state for backward compatibility
    set({
      autoSaveTimer: null,
      autoSaveDebounceTimer: null,
    })
  },

  setDeployedAt: (deployedAt: string | null) => {
    set({ deployedAt })
  },

  exportGraph: () => {
    const { nodes, edges, rfInstance } = get()
    const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }

    const nodesWithSizes = nodes.map((node) => {
      const nodeCopy = { ...node }
      if (!nodeCopy.width || nodeCopy.width === 0) {
        nodeCopy.width = 140
      }
      if (!nodeCopy.height || nodeCopy.height === 0) {
        nodeCopy.height = 100
      }
      if (!nodeCopy.positionAbsolute) {
        nodeCopy.positionAbsolute = { ...nodeCopy.position }
      }
      return nodeCopy
    })

    const data = {
      version: '1.0',
      nodes: nodesWithSizes,
      edges,
      viewport,
      exportedAt: new Date().toISOString(),
    }
    const jsonString = JSON.stringify(data, null, 2)
    const blob = new Blob([jsonString], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `agent-flow-${new Date().getTime()}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  },

  importGraph: async (file: File) => {
    return new Promise<void>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = (e) => {
        try {
          const text = e.target?.result
          if (typeof text !== 'string') {
            throw new Error('Failed to read file')
          }

          const data = JSON.parse(text)

          if (!data.nodes || !Array.isArray(data.nodes)) {
            throw new Error('Invalid graph format: missing nodes array')
          }
          if (!data.edges || !Array.isArray(data.edges)) {
            throw new Error('Invalid graph format: missing edges array')
          }

          const nodesWithSizes = data.nodes.map((node: Node) => {
            const nodeCopy = { ...node }
            if (!nodeCopy.width || nodeCopy.width === 0) {
              nodeCopy.width = 140
            }
            if (!nodeCopy.height || nodeCopy.height === 0) {
              nodeCopy.height = 100
            }
            if (!nodeCopy.positionAbsolute) {
              nodeCopy.positionAbsolute = { ...nodeCopy.position }
            }
            if (!nodeCopy.position) {
              nodeCopy.position = { x: 0, y: 0 }
              nodeCopy.positionAbsolute = { x: 0, y: 0 }
            }
            return nodeCopy
          })

          get().takeSnapshot()

          const viewport = data.viewport || null

          // Import doesn't set graphId/graphName, so don't trigger auto-save
          // User needs to explicitly save the imported graph first
          set({
            nodes: nodesWithSizes,
            edges: data.edges,
            past: [],
            future: [],
            selectedNodeId: null,
            hasPendingChanges: false,
            lastSavedStateHash: null,
            saveRetryCount: 0,
            lastSaveError: null,
          })

          // Clear any existing import timers
          if (importGraphTimeout1) {
            clearTimeout(importGraphTimeout1)
            importGraphTimeout1 = null
          }
          if (importGraphTimeout2) {
            clearTimeout(importGraphTimeout2)
            importGraphTimeout2 = null
          }

          importGraphTimeout1 = setTimeout(() => {
            const { rfInstance } = get()
            if (viewport && rfInstance) {
              rfInstance.setViewport(viewport)
              importGraphTimeout1 = null
            } else if (rfInstance) {
              importGraphTimeout2 = setTimeout(() => {
                rfInstance?.fitView({ padding: 0.2 })
                importGraphTimeout2 = null
              }, 100)
              importGraphTimeout1 = null
            } else {
              importGraphTimeout1 = null
            }
          }, 100)

          resolve()
        } catch (error: unknown) {
          const message = error instanceof Error ? error.message : 'Failed to parse graph file'
          reject(new Error(message))
        }
      }

      reader.onerror = () => {
        reject(new Error('Failed to read file'))
      }

      reader.readAsText(file)
    })
  },

  applyAIChanges: ({ nodes, edges }) => {
    console.log('[BuilderStore] applyAIChanges called', {
      nodesProvided: nodes !== undefined,
      nodesLength: nodes?.length ?? 0,
      edgesProvided: edges !== undefined,
      edgesLength: edges?.length ?? 0,
      currentNodesCount: get().nodes.length,
      currentEdgesCount: get().edges.length,
    })

    get().takeSnapshot()
    set((state) => ({
      // Use explicit undefined check to allow empty arrays
      nodes: nodes !== undefined ? nodes : state.nodes,
      edges: edges !== undefined ? edges : state.edges,
    }))

    console.log('[BuilderStore] applyAIChanges completed', {
      newNodesCount: get().nodes.length,
      newEdgesCount: get().edges.length,
    })

    // ⭐ For Copilot actions, use immediate save instead of debounced save
    // This ensures data is saved immediately without waiting for the 2-second debounce delay
    const { graphId } = get()
    if (graphId) {
      saveManager.immediateSave().catch((error) => {
        console.error('[BuilderStore] Immediate save failed after applyAIChanges:', error)
        // Fallback to debounced save if immediate save fails
        get().triggerAutoSave()
      })
    } else {
      // If no graphId, fallback to triggerAutoSave (shouldn't happen in normal flow)
      get().triggerAutoSave()
    }
  },

  getGraphContext: () => {
    const { nodes, edges } = get()
    return {
      nodes: nodes,
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target
      })),
    }
  },

  // ========== Graph Variables Actions ==========

  updateGraphVariables: (variables) => {
    set({ graphVariables: variables, hasPendingChanges: true })
    get().triggerAutoSave()
  },

  setGraphVariable: (key, variable) => {
    set((state) => ({
      graphVariables: {
        ...state.graphVariables,
        [key]: variable,
      },
      hasPendingChanges: true,
    }))
    get().triggerAutoSave()
  },

  deleteGraphVariable: (key) => {
    set((state) => {
      const { [key]: _, ...rest } = state.graphVariables
      return {
        graphVariables: rest,
        hasPendingChanges: true,
      }
    })
    get().triggerAutoSave()
  },

  getGraphVariableKeys: () => {
    return Object.keys(get().graphVariables)
  },

  toggleGraphSettings: (show) => {
    set((state) => ({
      showGraphSettings: show !== undefined ? show : !state.showGraphSettings,
    }))
  },

  toggleValidationSummary: (show) => {
    set((state) => ({
      showValidationSummary: show !== undefined ? show : !state.showValidationSummary,
    }))
  },
  }
})

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
import { generateUUID } from '@/lib/utils/uuid'
import { useSidebarStore } from '@/stores/sidebar/store'
import { computeGraphStateHash } from '@/utils/graphStateHash'

import { agentService } from '../services/agentService'
import { nodeRegistry } from '../services/nodeRegistry'
import type { StateField } from '../types/graph'
import { EdgeData, ValidationError } from '../types/graph'
import { determineEdgeTypeAndRouteKey, autoWireConnection } from '../utils/connectionUtils'
import { getEdgeStyleByType, processEdgesForReactFlow } from '../utils/edgeStyles'
import { exportGraphToJson, parseImportedGraph } from '../utils/graphImportExport'
import { SaveManager, type GraphState as SaveManagerGraphState } from '../utils/saveManager'

/**
 * Migrate legacy context variables to state fields.
 * Converts variables.context entries to StateField[] format.
 * Only applies when state_fields is empty but context has entries.
 */
function migrateLegacyContextToStateFields(variables: Record<string, any>): StateField[] {
  const stateFields = (variables.state_fields as StateField[]) || []
  if (stateFields.length > 0) return stateFields

  const legacyContext = (variables.context || {}) as Record<string, any>
  if (Object.keys(legacyContext).length === 0) return []

  const migrated = Object.entries(legacyContext).map(([key, v]) => ({
    name: key,
    type: (v?.type === 'number'
      ? 'int'
      : v?.type === 'boolean'
        ? 'bool'
        : v?.type || 'string') as StateField['type'],
    description: v?.description || '',
    defaultValue: v?.value,
  }))
  console.warn('[builderStore] Migrated legacy context variables to state fields:', migrated.length)
  return migrated
}

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

  // Execution State
  isExecuting: boolean
  activeExecutionNodeId: string | null
  executionLogs: ExecutionLog[]

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

  // Actions
  initialize: (workspaceId: string, graphId: string, ref: ReactFlowInstance) => Promise<void>
  undo: () => void
  redo: () => void
  takeSnapshot: () => void

  // Node Actions
  addNode: (
    type: string,
    position: { x: number; y: number },
    label?: string,
    configOverride?: Record<string, unknown>,
  ) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  updateNodeLabel: (id: string, label: string) => void
  deleteNode: (id: string) => void
  duplicateNode: (id: string) => void
  selectNode: (id: string | null) => void

  // Edge Actions
  updateEdge: (id: string, data: Partial<EdgeData>) => void
  selectEdge: (id: string | null) => void
  getOutgoingEdges: (nodeId: string) => Edge[]

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


  // State Schema Actions
  graphStateFields: import('../types/graph').StateField[]
  addStateField: (field: import('../types/graph').StateField) => void
  updateStateField: (name: string, field: Partial<import('../types/graph').StateField>) => void
  deleteStateField: (name: string) => void
  fallbackNodeId: string | null
  setFallbackNodeId: (nodeId: string | null) => void
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
      graphStateFields: get().graphStateFields,
      fallbackNodeId: get().fallbackNodeId,
    }),
    {
      onSaveSuccess: (hash, savedGraphId) => {
        const currentGraphId = get().graphId
        if (savedGraphId && savedGraphId !== currentGraphId) return
        set({
          lastSavedStateHash: hash,
          lastAutoSaveTime: Date.now(),
          saveRetryCount: 0,
          lastSaveError: null,
        })
      },
      onSaveError: (error) => {
        set({ lastSaveError: error })
      },
    },
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
    graphStateFields: [],
    fallbackNodeId: null,
    setFallbackNodeId: (nodeId) => {
      set({ fallbackNodeId: nodeId })
      get().triggerAutoSave()
    },

    // Actions
    initialize: async (workspaceId, graphId, rfInstance) => {
      set({
        isInitializing: true,
        workspaceId,
        graphId,
        rfInstance,
        nodes: [],
        edges: [],
        graphStateFields: [],
      })

      try {
        const [graphState, graphs] = await Promise.all([
          agentService.loadGraphState(graphId),
          agentService.listGraphs(workspaceId),
        ])

        const graphMeta = graphs.find((g) => g.id === graphId)

        // Parse state fields and fallback_node_id from variables
        const variables = (graphState.variables || {}) as any
        const stateFields = migrateLegacyContextToStateFields(variables)
        const fallbackNodeId = variables?.fallback_node_id ?? null

        set({
          nodes: graphState.nodes || [],
          edges: graphState.edges || [],
          graphName: graphMeta?.name || 'Untitled Graph',
          deployedAt: graphMeta?.isDeployed ? new Date().toISOString() : null,
          graphStateFields: stateFields,
          fallbackNodeId: fallbackNodeId || null,
          lastSavedStateHash: computeGraphStateHash(
            graphState.nodes || [],
            graphState.edges || [],
            stateFields,
            fallbackNodeId,
          ),
          isInitializing: false,
        })

        // Initialize history
        get().takeSnapshot()

        // Center view if viewport exists, otherwise fit view
        if (graphState.viewport) {
          rfInstance.setViewport(graphState.viewport)
        } else {
          setTimeout(() => rfInstance.fitView({ padding: 0.2 }), 100)
        }
      } catch (error) {
        console.error('Failed to initialize graph:', error)
        set({ isInitializing: false })
      }
    },

    addStateField: (field) => {
      set((state) => ({
        graphStateFields: [...state.graphStateFields, field],
      }))
      get().triggerAutoSave()
    },

    updateStateField: (name, updates) => {
      set((state) => ({
        graphStateFields: state.graphStateFields.map((f) =>
          f.name === name ? { ...f, ...updates } : f,
        ),
      }))
      get().triggerAutoSave()
    },

    deleteStateField: (name) => {
      set((state) => ({
        graphStateFields: state.graphStateFields.filter((f) => f.name !== name),
      }))
      get().triggerAutoSave()
    },

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
        i18n
          .t('execution.agentStarted', {
            defaultValue: '智能体已启动，输入：{{input}}',
            input,
          })
          .replace('{{input}}', input),
        'info',
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
              'info',
            )
          }
        } else {
          currentNode = null
        }
      }

      if (get().isExecuting) {
        get().addLog(
          'system',
          i18n.t('execution.agentCompleted', { defaultValue: '智能体成功完成。' }),
          'success',
        )
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
      const isContentChange = changes.some(
        (c) => c.type !== 'select' && c.type !== 'dimensions',
      )
      if (isContentChange) get().triggerAutoSave()
    },

    onEdgesChange: (changes: EdgeChange[]) => {
      if (changes.some((c) => c.type === 'remove')) get().takeSnapshot()
      set({ edges: applyEdgeChanges(changes, get().edges) })
      const isContentChange = changes.some((c) => c.type !== 'select')
      if (isContentChange) get().triggerAutoSave()
    },

    onConnect: (connection: Connection) => {
      try {
        if (!connection.source || !connection.target) return

        const { edges, nodes } = get()
        const exists = edges.some(
          (e) => e.source === connection.source && e.target === connection.target,
        )
        if (exists) return

        if (connection.source === connection.target) return

        const sourceNode = nodes.find((n) => n.id === connection.source)
        const targetNode = nodes.find((n) => n.id === connection.target)
        if (!sourceNode || !targetNode) return

        // Determine edge type and route_key using extracted utility
        const { edgeType, routeKey } = determineEdgeTypeAndRouteKey(
          connection.source,
          connection.target,
          nodes,
          edges,
        )

        const edgeData: EdgeData = {
          edge_type: edgeType,
          route_key: routeKey,
        }

        const { style: edgeStyle } = getEdgeStyleByType(edgeType)

        get().takeSnapshot()
        set({
          edges: addEdge(
            {
              ...connection,
              data: edgeData,
              type: 'default',
              animated: true,
              style: edgeStyle,
            },
            get().edges,
          ),
        })

        get().triggerAutoSave()
      } catch (error) {
        console.error('Failed to create connection:', error)
      }
    },

    setRfInstance: (instance) => set({ rfInstance: instance }),
    setWorkspaceId: (workspaceId) => set({ workspaceId }),
    setGraphId: (graphId) => {
      set({ graphId })
    },
    setGraphName: (graphName) => set({ graphName }),

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
        id: generateUUID(),
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

      // Auto-sync removed (router_node deleted)

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
      const sidebarRightBoundary = isSidebarCollapsed ? 422 : sidebarWidth

      if (newX < sidebarRightBoundary + 50) {
        newX = sidebarRightBoundary + 50
      }

      const newNode: Node = {
        ...nodeToDuplicate,
        id: generateUUID(),
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
          const { type: edgeTypeForReactFlow, style: edgeStyle } = getEdgeStyleByType(
            edgeType,
            e.style,
          )

          return {
            ...e,
            type: edgeTypeForReactFlow,
            data: updatedData,
            style: edgeStyle,
          }
        }),
      }))
      get().triggerAutoSave()
    },
    selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),

    getOutgoingEdges: (nodeId) => {
      return get().edges.filter((e) => e.source === nodeId)
    },


    loadGraph: async (graphId?: string) => {
      set({ isInitializing: true })
      try {
        if (graphId) {
          const state = await agentService.loadGraphState(graphId)
          let { nodes, edges } = state
          const { variables } = state

          // Process edges to ensure correct type and style based on edge_type
          const processedEdges = processEdgesForReactFlow(edges)

          // Load state fields and fallback_node_id from variables
          const loadedStateFields = migrateLegacyContextToStateFields(
            (variables as Record<string, any>) || {},
          )
          const fallbackNodeId = (variables as any)?.fallback_node_id ?? null

          set({
            nodes,
            edges: processedEdges,
            graphStateFields: loadedStateFields,
            fallbackNodeId: fallbackNodeId || null,
            past: [],
            future: [],
            isInitializing: false,
          })
        } else {
          let { nodes, edges } = await agentService.getInitialGraph()

          // Process edges to ensure correct type and style based on edge_type
          const processedEdges = processEdgesForReactFlow(edges)

          set({ nodes, edges: processedEdges, past: [], future: [], isInitializing: false })
        }
      } catch {
        set({ nodes: [], edges: [], past: [], future: [], isInitializing: false })
      }
    },

    saveGraph: async (name: string) => {
      const { nodes, edges, rfInstance, workspaceId } = get()
      if (!name) return
      set({ isSaving: true })
      try {
        const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }
        const variables = {}
        const { graphId } = await agentService.saveGraph({
          name,
          nodes,
          edges,
          viewport,
          workspaceId,
          variables,
        })
        // Save state using SaveManager
        await saveManager.save('manual')
        const currentStateHash = computeGraphStateHash(nodes, edges, get().graphStateFields, get().fallbackNodeId)
        set({
          graphId,
          graphName: name,
          lastAutoSaveTime: Date.now(),
          lastSavedStateHash: currentStateHash,
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

      saveManager.debouncedSave()
    },

    startAutoSave: () => {
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
      exportGraphToJson(nodes, edges, rfInstance)
    },

    importGraph: async (file: File) => {
      try {
        const { nodes, edges, viewport } = await parseImportedGraph(file)

        get().takeSnapshot()

        // Import doesn't set graphId/graphName, so don't trigger auto-save
        // User needs to explicitly save the imported graph first
        set({
          nodes,
          edges,
          past: [],
          future: [],
          selectedNodeId: null,
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
      } catch (error) {
        throw error
      }
    },

    applyAIChanges: ({ nodes, edges }) => {
      console.warn('[BuilderStore] applyAIChanges called', {
        nodesProvided: nodes !== undefined,
        nodesLength: nodes?.length ?? 0,
        edgesProvided: edges !== undefined,
        edgesLength: edges?.length ?? 0,
        currentNodesCount: get().nodes.length,
        currentEdgesCount: get().edges.length,
      })

      get().takeSnapshot()
      set((state) => ({
        nodes: nodes !== undefined ? nodes : state.nodes,
        edges: edges !== undefined ? edges : state.edges,
      }))

      console.warn('[BuilderStore] applyAIChanges completed', {
        newNodesCount: get().nodes.length,
        newEdgesCount: get().edges.length,
      })

      // Optimistic update only. Graph state is persisted by the backend after
      // Copilot generation; no frontend save here to avoid dual-write races.
    },

    getGraphContext: () => {
      const { nodes, edges } = get()
      return {
        nodes: nodes,
        edges: edges.map((e) => ({
          source: e.source,
          target: e.target,
        })),
      }
    },
  }
})

// Subscribe to relevant fields and recompute hasPendingChanges reactively.
// This ensures useBuilderStore() hooks in components always see the correct value.
useBuilderStore.subscribe((state, prevState) => {
  if (
    state.nodes === prevState.nodes &&
    state.edges === prevState.edges &&
    state.graphStateFields === prevState.graphStateFields &&
    state.fallbackNodeId === prevState.fallbackNodeId &&
    state.lastSavedStateHash === prevState.lastSavedStateHash &&
    state.graphId === prevState.graphId
  ) return

  const { graphId, nodes, edges, graphStateFields, fallbackNodeId, lastSavedStateHash } = state
  let hasPendingChanges: boolean
  if (!graphId && nodes.length === 0 && edges.length === 0) {
    hasPendingChanges = false
  } else if (lastSavedStateHash === null) {
    hasPendingChanges = graphId !== null
  } else {
    const currentHash = computeGraphStateHash(nodes, edges, graphStateFields, fallbackNodeId)
    hasPendingChanges = currentHash !== lastSavedStateHash
  }
  if (state.hasPendingChanges !== hasPendingChanges) {
    // Safe: hasPendingChanges is not in the watched fields above, so this
    // setState call won't re-trigger the early-return check, preventing
    // infinite recursion.
    useBuilderStore.setState({ hasPendingChanges })
  }
})

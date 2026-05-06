'use client'

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

import { generateUUID } from '@/lib/utils/uuid'
import { createLogger } from '@/lib/logs/console/logger'
import { useSidebarStore } from '@/stores/sidebar/store'

import { nodeRegistry } from '../services/nodeRegistry'
import type { StateField } from '../types/graph'
import { EdgeData } from '../types/graph'
import { determineEdgeTypeAndRouteKey } from '../utils/connectionUtils'
import { getEdgeStyleByType, processEdgesForReactFlow } from '../utils/edgeStyles'
import { exportGraphToJson, parseImportedGraph } from '../utils/graphImportExport'

const logger = createLogger('GraphStore')

interface HistoryState {
  nodes: Node[]
  edges: Edge[]
}

let importGraphTimeout1: NodeJS.Timeout | null = null
let importGraphTimeout2: NodeJS.Timeout | null = null

interface GraphState {
  // Canvas State
  nodes: Node[]
  edges: Edge[]
  rfInstance: ReactFlowInstance | null
  selectedNodeId: string | null
  selectedEdgeId: string | null

  // History State
  past: HistoryState[]
  future: HistoryState[]

  // Identity fields
  agentId: string | null
  versionId: string | null
  workspaceId: string | null
  graphId: string | null
  graphName: string | null

  // Graph schema
  graphStateFields: StateField[]
  fallbackNodeId: string | null

  // UI State
  isInitializing: boolean

  // ReactFlow handlers
  onNodesChange: OnNodesChange
  onEdgesChange: OnEdgesChange
  onConnect: OnConnect
  setRfInstance: (instance: ReactFlowInstance) => void

  // Selection
  selectNode: (id: string | null) => void
  selectEdge: (id: string | null) => void
  clearSelection: () => void

  // History
  undo: () => void
  redo: () => void
  takeSnapshot: () => void

  // Identity setters
  setWorkspaceId: (workspaceId: string) => void
  setGraphId: (graphId: string | null) => void
  setGraphName: (graphName: string | null) => void

  // Direct setters
  setNodes: (nodes: Node[]) => void
  setEdges: (edges: Edge[]) => void

  // Node actions
  addNode: (
    type: string,
    position: { x: number; y: number },
    label?: string,
    configOverride?: Record<string, unknown>,
  ) => void
  updateNodeData: (id: string, data: Partial<Record<string, unknown>>) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  updateNodeLabel: (id: string, label: string) => void
  deleteNode: (id: string) => void
  duplicateNode: (id: string) => void

  // Edge actions
  updateEdge: (id: string, data: Partial<EdgeData>) => void
  getOutgoingEdges: (nodeId: string) => Edge[]

  // Graph persistence
  loadGraph: () => Promise<void>
  exportGraph: () => void
  importGraph: (file: File) => Promise<void>

  // AI integration
  applyAIChanges: (changes: { nodes?: Node[]; edges?: Edge[] }) => void
  getGraphContext: () => { nodes: Node[]; edges: { source: string; target: string }[] }

  // State schema
  addStateField: (field: StateField) => void
  updateStateField: (name: string, field: Partial<StateField>) => void
  deleteStateField: (name: string) => void
  setFallbackNodeId: (nodeId: string | null) => void
}

export type { GraphState }

let _triggerAutoSave: (() => void) | null = null

export function setAutoSaveTrigger(fn: () => void) {
  _triggerAutoSave = fn
}

function triggerAutoSave() {
  _triggerAutoSave?.()
}

export const useGraphStore = create<GraphState>((set, get) => ({
  nodes: [],
  edges: [],
  rfInstance: null,
  selectedNodeId: null,
  selectedEdgeId: null,
  past: [],
  future: [],
  agentId: null,
  versionId: null,
  workspaceId: null,
  graphId: null,
  graphName: null,
  graphStateFields: [],
  fallbackNodeId: null,
  isInitializing: false,

  onNodesChange: (changes: NodeChange[]) => {
    if (changes.some((c) => c.type === 'remove')) get().takeSnapshot()
    set({ nodes: applyNodeChanges(changes, get().nodes) })
    const isContentChange = changes.some((c) => c.type !== 'select' && c.type !== 'dimensions')
    if (isContentChange) triggerAutoSave()
  },

  onEdgesChange: (changes: EdgeChange[]) => {
    if (changes.some((c) => c.type === 'remove')) get().takeSnapshot()
    set({ edges: applyEdgeChanges(changes, get().edges) })
    const isContentChange = changes.some((c) => c.type !== 'select')
    if (isContentChange) triggerAutoSave()
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

      triggerAutoSave()
    } catch (error) {
      logger.error('Failed to create connection:', error)
    }
  },

  setRfInstance: (instance) => set({ rfInstance: instance }),

  selectNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),
  clearSelection: () => set({ selectedNodeId: null, selectedEdgeId: null }),

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
    triggerAutoSave()
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
    triggerAutoSave()
  },

  setWorkspaceId: (workspaceId) => set({ workspaceId }),
  setGraphId: (graphId) => set({ graphId }),
  setGraphName: (graphName) => set({ graphName }),
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  addNode: (type, position, label, configOverride) => {
    get().takeSnapshot()
    const def = nodeRegistry.get(type)
    const defaultConfig = { ...def?.defaultConfig }
    if (configOverride) {
      Object.assign(defaultConfig, configOverride)
    }
    const newNode: Node = {
      id: generateUUID(),
      type: 'custom',
      position,
      data: {
        label: label || def?.label || 'New Node',
        type,
        config: defaultConfig,
      },
    }
    set({ nodes: [...get().nodes, newNode], selectedNodeId: newNode.id })
    triggerAutoSave()
  },

  updateNodeData: (id, data) => {
    set({
      nodes: get().nodes.map((n) => {
        if (n.id !== id) return n
        return { ...n, data: { ...n.data, ...data } }
      }),
    })
  },

  updateNodeConfig: (id, config) => {
    set({
      nodes: get().nodes.map((n) => {
        if (n.id !== id) return n
        const nodeData = n.data as { config?: Record<string, unknown> }
        return { ...n, data: { ...n.data, config: { ...nodeData.config, ...config } } }
      }),
    })
    triggerAutoSave()
  },

  updateNodeLabel: (id, label) => {
    set({
      nodes: get().nodes.map((node) => {
        if (node.id !== id) return node
        return { ...node, data: { ...node.data, label } }
      }),
    })
    triggerAutoSave()
  },

  deleteNode: (id) => {
    get().takeSnapshot()
    const { nodes, edges } = get()
    set({
      nodes: nodes.filter((n) => n.id !== id),
      edges: edges.filter((e) => e.source !== id && e.target !== id),
      selectedNodeId: null,
    })
    triggerAutoSave()
  },

  duplicateNode: (id) => {
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
    triggerAutoSave()
  },

  // Edge actions
  updateEdge: (id, data) => {
    set((state) => ({
      edges: state.edges.map((e) => {
        if (e.id !== id) return e
        const updatedData = { ...(e.data || {}), ...data } as EdgeData
        const edgeType = updatedData.edge_type
        const { type: edgeTypeForReactFlow, style: edgeStyle } = getEdgeStyleByType(
          edgeType,
          e.style,
        )
        return { ...e, type: edgeTypeForReactFlow, data: updatedData, style: edgeStyle }
      }),
    }))
    triggerAutoSave()
  },

  getOutgoingEdges: (nodeId) => {
    return get().edges.filter((e) => e.source === nodeId)
  },

  // Graph persistence
  loadGraph: async () => {
    set({ isInitializing: true })
    try {
      const processedEdges = processEdgesForReactFlow([])
      set({ nodes: [], edges: processedEdges, past: [], future: [], isInitializing: false })
    } catch {
      set({ nodes: [], edges: [], past: [], future: [], isInitializing: false })
    }
  },

  exportGraph: () => {
    const { nodes, edges, rfInstance } = get()
    exportGraphToJson(nodes, edges, rfInstance)
  },

  importGraph: async (file: File) => {
    const { nodes, edges, viewport } = await parseImportedGraph(file)

    get().takeSnapshot()

    set({
      nodes,
      edges,
      past: [],
      future: [],
      selectedNodeId: null,
    })

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
  },

  // AI integration
  applyAIChanges: ({ nodes, edges }) => {
    get().takeSnapshot()
    set((state) => ({
      nodes: nodes !== undefined ? nodes : state.nodes,
      edges: edges !== undefined ? edges : state.edges,
    }))
  },

  getGraphContext: () => {
    const { nodes, edges } = get()
    return {
      nodes,
      edges: edges.map((e) => ({ source: e.source, target: e.target })),
    }
  },

  // State schema
  addStateField: (field) => {
    set((state) => ({ graphStateFields: [...state.graphStateFields, field] }))
    triggerAutoSave()
  },

  updateStateField: (name, updates) => {
    set((state) => ({
      graphStateFields: state.graphStateFields.map((f) =>
        f.name === name ? { ...f, ...updates } : f,
      ),
    }))
    triggerAutoSave()
  },

  deleteStateField: (name) => {
    set((state) => ({
      graphStateFields: state.graphStateFields.filter((f) => f.name !== name),
    }))
    triggerAutoSave()
  },

  setFallbackNodeId: (nodeId) => {
    set({ fallbackNodeId: nodeId })
    triggerAutoSave()
  },
}))

const graphStoreInitialState = useGraphStore.getState()
;(useGraphStore as unknown as { getInitialState: () => GraphState }).getInitialState = () =>
  graphStoreInitialState

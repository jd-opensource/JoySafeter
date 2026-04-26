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

import { nodeRegistry } from '../services/nodeRegistry'
import type { StateField } from '../types/graph'
import { EdgeData } from '../types/graph'
import { determineEdgeTypeAndRouteKey } from '../utils/connectionUtils'
import { getEdgeStyleByType } from '../utils/edgeStyles'

const logger = createLogger('GraphStore')

interface HistoryState {
  nodes: Node[]
  edges: Edge[]
}

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

  // Selection
  selectNode: (id: string | null) => void
  selectEdge: (id: string | null) => void
  clearSelection: () => void

  // History
  undo: () => void
  redo: () => void
  pushHistory: () => void

  // Identity setters
  setWorkspaceId: (workspaceId: string) => void

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
  removeNode: (id: string) => void
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
    if (changes.some((c) => c.type === 'remove')) get().pushHistory()
    set({ nodes: applyNodeChanges(changes, get().nodes) })
  },

  onEdgesChange: (changes: EdgeChange[]) => {
    if (changes.some((c) => c.type === 'remove')) get().pushHistory()
    set({ edges: applyEdgeChanges(changes, get().edges) })
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

      get().pushHistory()
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
    } catch (error) {
      logger.error('Failed to create connection:', error)
    }
  },

  selectNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),
  clearSelection: () => set({ selectedNodeId: null, selectedEdgeId: null }),

  pushHistory: () => {
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
  },

  setWorkspaceId: (workspaceId) => set({ workspaceId }),
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  addNode: (type, position, label, configOverride) => {
    get().pushHistory()
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
  },

  updateNodeData: (id, data) => {
    set({
      nodes: get().nodes.map((n) => {
        if (n.id !== id) return n
        return { ...n, data: { ...n.data, ...data } }
      }),
    })
  },

  removeNode: (id) => {
    get().pushHistory()
    const { nodes, edges } = get()
    set({
      nodes: nodes.filter((n) => n.id !== id),
      edges: edges.filter((e) => e.source !== id && e.target !== id),
      selectedNodeId: null,
    })
  },
}))

// Expose getInitialState for test resets
;(useGraphStore as unknown as { getInitialState: () => GraphState }).getInitialState = () => ({
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
  onNodesChange: useGraphStore.getState().onNodesChange,
  onEdgesChange: useGraphStore.getState().onEdgesChange,
  onConnect: useGraphStore.getState().onConnect,
  selectNode: useGraphStore.getState().selectNode,
  selectEdge: useGraphStore.getState().selectEdge,
  clearSelection: useGraphStore.getState().clearSelection,
  pushHistory: useGraphStore.getState().pushHistory,
  undo: useGraphStore.getState().undo,
  redo: useGraphStore.getState().redo,
  setWorkspaceId: useGraphStore.getState().setWorkspaceId,
  setNodes: useGraphStore.getState().setNodes,
  setEdges: useGraphStore.getState().setEdges,
  addNode: useGraphStore.getState().addNode,
  updateNodeData: useGraphStore.getState().updateNodeData,
  removeNode: useGraphStore.getState().removeNode,
})

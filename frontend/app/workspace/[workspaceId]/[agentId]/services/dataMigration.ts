/**
 * Data Migration - Convert old graph data formats to new format
 * 
 * Handles migration of:
 * - Edge data: routeKey -> route_key
 * - Router node routes: target -> targetEdgeKey
 * - Other field name changes
 */

import { Node, Edge } from 'reactflow'

import { EdgeData, RouteRule } from '../types/graph'

/**
 * Migrate edge data format
 * - routeKey -> route_key
 * - edgeType -> edge_type
 */
export function migrateEdgeData(edge: Edge): Edge {
  const edgeData = (edge.data || {}) as any
  
  // Check if migration is needed
  const needsMigration = 
    edgeData.routeKey !== undefined ||
    edgeData.edgeType !== undefined ||
    edgeData.sourceHandleId !== undefined

  if (!needsMigration) {
    return edge
  }

  const migratedData: EdgeData & Record<string, any> = {
    ...edgeData,
  }

  // Migrate routeKey -> route_key
  if (edgeData.routeKey !== undefined && edgeData.route_key === undefined) {
    migratedData.route_key = edgeData.routeKey
    delete migratedData.routeKey
  }

  // Migrate edgeType -> edge_type
  if (edgeData.edgeType !== undefined && edgeData.edge_type === undefined) {
    migratedData.edge_type = edgeData.edgeType as EdgeData['edge_type']
    delete migratedData.edgeType
  }

  // Migrate sourceHandleId -> source_handle_id
  if (edgeData.sourceHandleId !== undefined && edgeData.source_handle_id === undefined) {
    migratedData.source_handle_id = edgeData.sourceHandleId
    delete migratedData.sourceHandleId
  }

  return {
    ...edge,
    data: migratedData as EdgeData,
  }
}

/**
 * Migrate router node routes format
 * - routes[].target -> routes[].targetEdgeKey
 */
export function migrateRouterNodeConfig(node: Node): Node {
  const nodeData = node.data as { type?: string; config?: Record<string, unknown> }
  
  if (nodeData.type !== 'router_node' || !nodeData.config) {
    return node
  }

  const config = nodeData.config
  const routes = config.routes as any[] | undefined

  if (!routes || !Array.isArray(routes)) {
    return node
  }

  // Check if migration is needed
  const needsMigration = routes.some((r) => r.target !== undefined && r.targetEdgeKey === undefined)

  if (!needsMigration) {
    return node
  }

  // Migrate routes
  const migratedRoutes: RouteRule[] = routes.map((route) => {
    const migrated: RouteRule = {
      id: route.id || `route_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      condition: route.condition || '',
      targetEdgeKey: route.targetEdgeKey || route.target || '',
      label: route.label || '',
      priority: route.priority,
    }
    return migrated
  })

  return {
    ...node,
    data: {
      ...nodeData,
      config: {
        ...config,
        routes: migratedRoutes,
      },
    },
  }
}

/**
 * Migrate all nodes and edges to new format
 */
export function migrateGraphData(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  // Migrate nodes
  const migratedNodes = nodes.map((node) => {
    // Migrate router node config
    return migrateRouterNodeConfig(node)
  })

  // Migrate edges
  const migratedEdges = edges.map((edge) => {
    return migrateEdgeData(edge)
  })

  return {
    nodes: migratedNodes,
    edges: migratedEdges,
  }
}

/**
 * Check if graph data needs migration
 */
export function needsMigration(nodes: Node[], edges: Edge[]): boolean {
  // Check edges
  const edgeNeedsMigration = edges.some((edge) => {
    const edgeData = (edge.data || {}) as any
    return (
      edgeData.routeKey !== undefined ||
      edgeData.edgeType !== undefined ||
      edgeData.sourceHandleId !== undefined
    )
  })

  // Check nodes
  const nodeNeedsMigration = nodes.some((node) => {
    const nodeData = node.data as { type?: string; config?: Record<string, unknown> }
    if (nodeData.type === 'router_node' && nodeData.config) {
      const routes = nodeData.config.routes as any[] | undefined
      if (routes && Array.isArray(routes)) {
        return routes.some((r) => r.target !== undefined && r.targetEdgeKey === undefined)
      }
    }
    return false
  })

  return edgeNeedsMigration || nodeNeedsMigration
}


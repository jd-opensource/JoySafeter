/**
 * Connection utilities for DeepAgents canvas.
 *
 * Simplified: DeepAgents only uses normal edges between agent nodes.
 */
import type { Edge, Node } from 'reactflow'

import type { EdgeData } from '../types/graph'

interface EdgeTypeResult {
  edgeType: EdgeData['edge_type']
  routeKey: string | undefined
}

/**
 * Determine edge type for a new connection.
 * DeepAgents only uses normal edges.
 */
export function determineEdgeTypeAndRouteKey(
  _sourceId: string,
  _targetId: string,
  _nodes: Node[],
  _edges: Edge[],
): EdgeTypeResult {
  return { edgeType: 'normal', routeKey: undefined }
}

/**
 * Auto-wire a new connection (no-op for DeepAgents).
 */
export function autoWireConnection(
  _sourceId: string,
  _targetId: string,
  _nodes: Node[],
  _edges: Edge[],
): EdgeData | null {
  return null
}

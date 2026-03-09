/**
 * Graph State Hash Utility
 *
 * Computes a hash of graph state (nodes and edges) for comparison purposes.
 * Used to avoid unnecessary saves when state hasn't changed.
 */

import type { Node, Edge } from 'reactflow'

/**
 * Compute a hash of the graph state for comparison
 *
 * Includes node id/position/data and edge source/target/data so that
 * changes to edge config (e.g. route_key, edge_type, source_handle_id)
 * trigger a save and are not lost.
 *
 * @param nodes - Array of graph nodes
 * @param edges - Array of graph edges
 * @param stateFields - Optional graph state fields
 * @returns A string hash representing the current state
 */
export function computeGraphStateHash(
  nodes: Node[],
  edges: Edge[],
  stateFields?: any[],
  fallbackNodeId?: string | null
): string {
  const stateForHash = {
    nodes: nodes.map(n => ({
      id: n.id,
      position: n.position,
      data: n.data,
    })),
    edges: edges.map(e => ({
      source: e.source,
      target: e.target,
      data: e.data ?? {},
    })),
    stateFields,
    fallbackNodeId: fallbackNodeId ?? undefined,
  }
  return JSON.stringify(stateForHash)
}

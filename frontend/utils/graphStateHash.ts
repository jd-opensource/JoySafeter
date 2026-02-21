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
 * @param nodes - Array of graph nodes
 * @param edges - Array of graph edges
 * @returns A string hash representing the current state
 */
export function computeGraphStateHash(
  nodes: Node[],
  edges: Edge[],
  stateFields?: any[]
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
    })),
    stateFields
  }
  return JSON.stringify(stateForHash)
}

/**
 * Action Processor - Unified action processing logic for Copilot.
 * 
 * Provides a centralized way to process graph actions and apply them
 * to the current graph state.
 */

import { Node, Edge } from 'reactflow'

import { nodeRegistry } from '@/app/workspace/[workspaceId]/[agentId]/services/nodeRegistry'
import type { GraphAction } from '@/types/copilot'

export interface ProcessedGraph {
  nodes: Node[]
  edges: Edge[]
}

export class ActionProcessor {
  /**
   * Process graph actions and return updated nodes and edges.
   * 
   * @param actions - Array of graph actions to process
   * @param currentNodes - Current nodes in the graph
   * @param currentEdges - Current edges in the graph
   * @returns Updated nodes and edges after processing all actions
   */
  static processActions(
    actions: GraphAction[],
    currentNodes: Node[],
    currentEdges: Edge[]
  ): ProcessedGraph {
    // Clone current state to apply diffs
    let processedNodes: Node[] = [...currentNodes]
    let processedEdges: Edge[] = [...currentEdges]

    actions.forEach((action) => {
      switch (action.type) {
        case 'CREATE_NODE': {
          const { id, type, label, position, config } = action.payload
          const def = nodeRegistry.get(type || '')
          const baseConfig = def ? { ...def.defaultConfig } : {}

          processedNodes.push({
            id: id || `ai_${Date.now()}`,
            type: 'custom',
            position: position || { x: 0, y: 0 },
            data: {
              label: label || def?.label || 'Node',
              type: type,
              config: { ...baseConfig, ...config },
            },
          })
          break
        }
        case 'CONNECT_NODES': {
          const { source, target } = action.payload
          if (
            source &&
            target &&
            !processedEdges.some((e) => e.source === source && e.target === target)
          ) {
            processedEdges.push({
              id: `e-${source}-${target}`,
              source,
              target,
              animated: true,
              style: { stroke: '#cbd5e1', strokeWidth: 1.5 },
            })
          }
          break
        }
        case 'DELETE_NODE': {
          processedNodes = processedNodes.filter((n) => n.id !== action.payload.id)
          processedEdges = processedEdges.filter(
            (e) => e.source !== action.payload.id && e.target !== action.payload.id
          )
          break
        }
        case 'UPDATE_CONFIG': {
          processedNodes = processedNodes.map((n) => {
            if (n.id === action.payload.id) {
              const nodeData = n.data as { config?: Record<string, unknown> }
              return {
                ...n,
                data: {
                  ...n.data,
                  config: { ...nodeData.config, ...action.payload.config },
                },
              }
            }
            return n
          })
          break
        }
        case 'UPDATE_POSITION': {
          // Update node position (from auto_layout tool)
          processedNodes = processedNodes.map((n) => {
            if (n.id === action.payload.id && action.payload.position) {
              return {
                ...n,
                position: action.payload.position,
              }
            }
            return n
          })
          break
        }
      }
    })

    return {
      nodes: processedNodes,
      edges: processedEdges,
    }
  }
}

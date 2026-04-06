/**
 * useActionExecutor - Hook for executing graph actions
 */

import { useState, useCallback } from 'react'
import { Node, Edge } from 'reactflow'

import { useBuilderStore } from '@/app/workspace/[workspaceId]/[agentId]/stores/builderStore'
import type { GraphAction } from '@/types/copilot'
import { ActionProcessor } from '@/lib/utils/copilot/actionProcessor'

export function useActionExecutor(expectedGraphId?: string) {
  const [executingActions, setExecutingActions] = useState(false)
  const { applyAIChanges } = useBuilderStore()

  const executeActions = useCallback(
    async (actions: GraphAction[]) => {
      const currentState = useBuilderStore.getState()
      const currentGraphId = currentState.graphId

      if (expectedGraphId && currentGraphId !== expectedGraphId) {
        console.warn('[useActionExecutor] graphId mismatch, skipping actions', {
          expectedGraphId,
          currentGraphId,
          actionsCount: actions.length,
        })
        return
      }

      console.warn('[useActionExecutor] executeActions called', {
        actionsCount: actions.length,
        actions: actions,
        currentNodesCount: currentState.nodes.length,
        currentEdgesCount: currentState.edges.length,
      })

      setExecutingActions(true)

      // Use ActionProcessor to process actions
      const currentNodes: Node[] = [...currentState.nodes]
      const currentEdges: Edge[] = [...currentState.edges]

      const { nodes: processedNodes, edges: processedEdges } = ActionProcessor.processActions(
        actions,
        currentNodes,
        currentEdges,
      )

      console.warn('[useActionExecutor] Actions processed', {
        newNodesCount: processedNodes.length,
        newEdgesCount: processedEdges.length,
        nodesAdded: processedNodes.length - currentNodes.length,
        edgesAdded: processedEdges.length - currentEdges.length,
      })

      // Apply to store
      console.warn('[useActionExecutor] Calling applyAIChanges', {
        nodes: processedNodes.length,
        edges: processedEdges.length,
      })
      applyAIChanges({ nodes: processedNodes, edges: processedEdges })
      console.warn('[useActionExecutor] applyAIChanges completed')

      setExecutingActions(false)
    },
    [applyAIChanges, expectedGraphId],
  )

  return {
    executingActions,
    executeActions,
  }
}

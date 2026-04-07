/**
 * useActionExecutor - Hook for executing graph actions
 */

import { useState, useCallback } from 'react'
import { Node, Edge } from 'reactflow'

import { useBuilderStore } from '@/app/workspace/[workspaceId]/[agentId]/stores/builderStore'
import type { GraphAction } from '@/types/copilot'
import { createLogger } from '@/lib/logs/console/logger'
import { ActionProcessor } from '@/lib/utils/copilot/actionProcessor'

const logger = createLogger('useActionExecutor')

export function useActionExecutor(expectedGraphId?: string) {
  const [executingActions, setExecutingActions] = useState(false)
  const { applyAIChanges } = useBuilderStore()

  const executeActions = useCallback(
    async (actions: GraphAction[]) => {
      const currentState = useBuilderStore.getState()
      const currentGraphId = currentState.graphId

      if (expectedGraphId && currentGraphId !== expectedGraphId) {
        logger.debug('graphId mismatch, skipping actions', {
          expectedGraphId,
          currentGraphId,
          actionsCount: actions.length,
        })
        return
      }

      logger.debug('executeActions called', {
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

      logger.debug('Actions processed', {
        newNodesCount: processedNodes.length,
        newEdgesCount: processedEdges.length,
        nodesAdded: processedNodes.length - currentNodes.length,
        edgesAdded: processedEdges.length - currentEdges.length,
      })

      // Apply to store
      logger.debug('Calling applyAIChanges', {
        nodes: processedNodes.length,
        edges: processedEdges.length,
      })
      applyAIChanges({ nodes: processedNodes, edges: processedEdges })
      logger.debug('applyAIChanges completed')

      setExecutingActions(false)
    },
    [applyAIChanges, expectedGraphId],
  )

  return {
    executingActions,
    executeActions,
  }
}

/**
 * useActionExecutor - Hook for executing graph actions
 */

import { useState } from 'react'
import { Node, Edge } from 'reactflow'

import { useBuilderStore } from '@/app/workspace/[workspaceId]/[agentId]/stores/builderStore'
import type { GraphAction } from '@/types/copilot'
import { ActionProcessor } from '@/utils/copilot/actionProcessor'

export function useActionExecutor() {
  const [executingActions, setExecutingActions] = useState(false)
  const { applyAIChanges } = useBuilderStore()

  const executeActions = async (actions: GraphAction[]) => {
    console.log('[useActionExecutor] executeActions called', {
      actionsCount: actions.length,
      actions: actions,
      currentNodesCount: useBuilderStore.getState().nodes.length,
      currentEdgesCount: useBuilderStore.getState().edges.length,
    })

    setExecutingActions(true)

    // Use ActionProcessor to process actions
    const currentNodes: Node[] = [...useBuilderStore.getState().nodes]
    const currentEdges: Edge[] = [...useBuilderStore.getState().edges]

    const { nodes: processedNodes, edges: processedEdges } = ActionProcessor.processActions(
      actions,
      currentNodes,
      currentEdges
    )

    console.log('[useActionExecutor] Actions processed', {
      newNodesCount: processedNodes.length,
      newEdgesCount: processedEdges.length,
      nodesAdded: processedNodes.length - currentNodes.length,
      edgesAdded: processedEdges.length - currentEdges.length,
    })

    // Apply to store
    console.log('[useActionExecutor] Calling applyAIChanges', {
      nodes: processedNodes.length,
      edges: processedEdges.length,
    })
    applyAIChanges({ nodes: processedNodes, edges: processedEdges })
    console.log('[useActionExecutor] applyAIChanges completed')

    setExecutingActions(false)
  }

  return {
    executingActions,
    executeActions,
  }
}

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import {
  agentService,
  type AgentGraph,
} from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { useBuilderStore } from '@/app/workspace/[workspaceId]/[agentId]/stores/builderStore'
import { CODE_STARTER_TEMPLATE } from '@/app/workspace/[workspaceId]/[agentId]/utils/codeTemplate'
import { useToast } from '@/hooks/use-toast'
import { graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('Sidebar')

export function useAgentMutations(workspaceId: string) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const createAgentMutation = useMutation({
    mutationFn: async (data: { name: string; description?: string; color?: string; mode?: 'canvas' | 'code' }) => {
      // Create Graph
      const graph = await agentService.createGraph({
        name: data.name,
        description: data.description,
        color: data.color,
        workspaceId: workspaceId || null,
      })

      if (graph?.id) {
        if (data.mode === 'code') {
          // Code mode: save with starter template and graph_mode flag
          await agentService.saveGraphState({
            graphId: graph.id,
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
            variables: {
              graph_mode: 'code',
              code_content: CODE_STARTER_TEMPLATE,
            },
          })
        } else {
          await agentService.saveGraphState({
            graphId: graph.id,
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
          })
        }
      }
      return graph
    },
    onSuccess: (graph: AgentGraph) => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      toast({
        title: t('workspace.agentCreateSuccess'),
        variant: 'success',
      })
      return graph
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.cannotCreateAgent')
      if (error instanceof Error) {
        const isPermissionError =
          error.message.includes('403') ||
          error.message.includes('permission') ||
          error.message.includes('Forbidden') ||
          error.message.includes('insufficient') ||
          error.message.includes('Insufficient')

        if (isPermissionError) {
          errorMessage = t('workspace.cannotCreateAgent')
        } else {
          errorMessage = error.message || errorMessage
        }
      }
      toast({
        title: t('workspace.agentCreateFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const updateAgentMutation = useMutation({
    mutationFn: async (data: {
      id: string
      name?: string
      description?: string
      color?: string
    }) => {
      await agentService.updateGraph(data.id, {
        name: data.name,
        description: data.description,
        color: data.color,
      })
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      // If renaming the currently editing graph, update graphName in store
      const { graphId, setGraphName } = useBuilderStore.getState()
      if (variables.name && graphId === variables.id) {
        setGraphName(variables.name)
        // Also update localStorage for compatibility
        agentService.setCachedGraphName(variables.name)
      }
      toast({
        title: t('workspace.agentUpdateSuccess'),
        variant: 'success',
      })
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.agentUpdateFailed')
      if (error instanceof Error) {
        errorMessage = error.message || errorMessage
      }
      toast({
        title: t('workspace.agentUpdateFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const deleteAgentMutation = useMutation({
    mutationFn: async (id: string) => {
      await agentService.deleteGraph(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      toast({
        title: t('workspace.agentDeleteSuccess'),
        variant: 'success',
      })
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.cannotDeleteAgent')
      if (error instanceof Error) {
        const isPermissionError =
          error.message.includes('403') ||
          error.message.includes('permission') ||
          error.message.includes('Forbidden') ||
          error.message.includes('insufficient') ||
          error.message.includes('Insufficient')

        if (isPermissionError) {
          errorMessage = t('workspace.cannotDeleteAgent')
        } else {
          errorMessage = error.message || errorMessage
        }
      }
      toast({
        title: t('workspace.agentDeleteFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const duplicateAgentMutation = useMutation({
    mutationFn: async (id: string) => {
      await agentService.duplicateGraph(id, { workspaceId: workspaceId || null })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      toast({
        title: t('workspace.agentDuplicateSuccess'),
        variant: 'success',
      })
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.agentDuplicateFailed')
      if (error instanceof Error) {
        const isPermissionError =
          error.message.includes('403') ||
          error.message.includes('permission') ||
          error.message.includes('Forbidden') ||
          error.message.includes('insufficient') ||
          error.message.includes('Insufficient')

        if (isPermissionError) {
          errorMessage = t('workspace.cannotCreateAgent')
        } else {
          errorMessage = error.message || errorMessage
        }
      }
      toast({
        title: t('workspace.agentDuplicateFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const handleMoveAgentToFolder = useCallback(
    async (agentId: string, folderId: string | null) => {
      try {
        await agentService.moveToFolder(agentId, folderId)
        queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      } catch (error) {
        logger.error('Failed to move agent to folder', { error, agentId, folderId })
      }
    },
    [workspaceId, queryClient],
  )

  return {
    createAgentMutation,
    updateAgentMutation,
    deleteAgentMutation,
    duplicateAgentMutation,
    handleMoveAgentToFolder,
  }
}

/**
 * Default Chat Mode Handler
 *
 * Handles default chat mode: create_deep_agent with all user-available skills, Docker backend.
 * Creates or reuses a "Default Chat" graph from the default-chat template.
 */

import { agentService } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { graphTemplateService } from '@/app/workspace/[workspaceId]/[agentId]/services/graphTemplateService'
import { graphKeys } from '@/hooks/queries/graphs'
import { toastError, toastSuccess } from '@/lib/utils/toast'

import { MessageSquare } from 'lucide-react'

import { getModeConfig } from '../../config/modeConfig'

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  ModeMetadata,
  UploadedFile,
} from './types'

const TEMPLATE_GRAPH_NAME = 'Default Chat'

let creatingGraphPromise: Promise<ModeSelectionResult> | null = null

export const defaultChatModeHandler: ModeHandler = {
  metadata: {
    id: 'default-chat',
    label: 'chat.defaultChat',
    description: 'chat.defaultChatDescription',
    icon: MessageSquare,
    type: 'template',
  },

  requiresFiles: false,

  async onSelect(context: ModeContext): Promise<ModeSelectionResult> {
    if (!context.personalWorkspaceId) {
      return {
        success: false,
        error: 'Personal workspace not found. Please ensure you have a personal workspace.',
      }
    }

    let workspaceGraphs: Array<{ id: string; name: string }> | undefined
    if (context.queryClient.getQueryData) {
      workspaceGraphs = context.queryClient.getQueryData<Array<{ id: string; name: string }>>(
        [...graphKeys.list(context.personalWorkspaceId)]
      )
    }

    if (!workspaceGraphs) {
      try {
        workspaceGraphs = await agentService.listGraphs(context.personalWorkspaceId)
      } catch (error) {
        console.error('Failed to fetch workspace graphs:', error)
        workspaceGraphs = []
      }
    }

    const defaultChatGraph = workspaceGraphs?.find((g) => g.name === TEMPLATE_GRAPH_NAME)

    if (defaultChatGraph) {
      return {
        success: true,
        stateUpdates: {
          mode: 'default-chat',
          graphId: defaultChatGraph.id,
        },
      }
    }

    if (creatingGraphPromise) {
      return creatingGraphPromise
    }

    const modeConfig = getModeConfig('default-chat')
    if (!modeConfig?.templateName || !modeConfig.templateGraphName) {
      return {
        success: false,
        error: 'Default Chat template configuration not found',
      }
    }

    creatingGraphPromise = (async (): Promise<ModeSelectionResult> => {
      try {
        if (context.queryClient.refetchQueries) {
          await context.queryClient.refetchQueries({
            queryKey: [...graphKeys.list(context.personalWorkspaceId!)],
          })
        }

        if (context.queryClient.getQueryData) {
          const queryData = context.queryClient.getQueryData<Array<{ id: string; name: string }>>(
            [...graphKeys.list(context.personalWorkspaceId!)]
          )
          const existing = queryData?.find((g) => g.name === TEMPLATE_GRAPH_NAME)
          if (existing) {
            return {
              success: true,
              stateUpdates: {
                mode: 'default-chat',
                graphId: existing.id,
              },
            }
          }
        }

        const createdGraph = await graphTemplateService.createGraphFromTemplate(
          modeConfig.templateName,
          modeConfig.templateGraphName,
          context.personalWorkspaceId!
        )

        if (context.queryClient.refetchQueries) {
          await context.queryClient.refetchQueries({
            queryKey: [...graphKeys.list(context.personalWorkspaceId!)],
          })
        }

        toastSuccess('Default Chat graph created successfully', 'Graph Initialized')

        return {
          success: true,
          stateUpdates: {
            mode: 'default-chat',
            graphId: createdGraph.id,
          },
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to create Default Chat graph'
        toastError(message, 'Graph Creation Failed')
        return {
          success: false,
          error: message,
        }
      } finally {
        creatingGraphPromise = null
      }
    })()

    return creatingGraphPromise
  },

  async onSubmit(
    input: string,
    files: UploadedFile[],
    context: ModeContext
  ): Promise<SubmitResult> {
    return {
      success: true,
      processedInput: input,
    }
  },

  validate(input: string, files: UploadedFile[]): ValidationResult {
    return { valid: true }
  },

  async getGraphId(context: ModeContext): Promise<string | null> {
    if (!context.personalWorkspaceId) {
      return null
    }

    let workspaceGraphs: Array<{ id: string; name: string }> | undefined
    if (context.queryClient.getQueryData) {
      workspaceGraphs = context.queryClient.getQueryData<Array<{ id: string; name: string }>>(
        [...graphKeys.list(context.personalWorkspaceId)]
      )
    }

    if (!workspaceGraphs) {
      try {
        workspaceGraphs = await agentService.listGraphs(context.personalWorkspaceId)
      } catch (error) {
        console.error('Failed to fetch workspace graphs:', error)
        return null
      }
    }

    const defaultChatGraph = workspaceGraphs?.find((g) => g.name === TEMPLATE_GRAPH_NAME)
    return defaultChatGraph?.id ?? null
  },
}

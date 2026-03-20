/**
 * Default Chat Mode Handler
 *
 * Handles default chat mode: create_deep_agent with all user-available skills, Docker backend.
 * Creates or reuses a "Default Chat" graph from the default-chat template.
 */

import { graphKeys } from '@/hooks/queries/graphs'

import { MessageSquare } from 'lucide-react'

import { getModeConfig } from '../../config/modeConfig'
import { findGraphByName, findOrCreateGraphByTemplate } from '../utils/graphLookup'

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  UploadedFile,
} from './types'

const TEMPLATE_GRAPH_NAME = 'Default Chat'

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

    const modeConfig = getModeConfig('default-chat')
    if (!modeConfig || !modeConfig.templateName || !modeConfig.templateGraphName) {
      return {
        success: false,
        error: 'Default Chat template configuration not found',
      }
    }

    try {
      const graph = await findOrCreateGraphByTemplate(
        modeConfig.templateGraphName,
        modeConfig.templateName,
        context.personalWorkspaceId,
      )

      // Refresh query cache so other UI components see the graph
      if (context.queryClient.refetchQueries) {
        await context.queryClient.refetchQueries({
          queryKey: [...graphKeys.list(context.personalWorkspaceId)],
        })
      } else {
        context.queryClient.invalidateQueries({
          queryKey: [...graphKeys.list(context.personalWorkspaceId)],
        })
      }

      return {
        success: true,
        stateUpdates: { mode: 'default-chat', graphId: graph.id },
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create Default Chat graph'
      return { success: false, error: message }
    }
  },

  async onSubmit(
    input: string,
    files: UploadedFile[],
    context: ModeContext,
  ): Promise<SubmitResult> {
    return { success: true, processedInput: input }
  },

  validate(input: string, files: UploadedFile[]): ValidationResult {
    return { valid: true }
  },

  async getGraphId(context: ModeContext): Promise<string | null> {
    const graph = await findGraphByName(TEMPLATE_GRAPH_NAME, context)
    return graph?.id ?? null
  },
}

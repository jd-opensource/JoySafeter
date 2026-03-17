/**
 * Default Chat Mode Handler
 *
 * Handles default chat mode: create_deep_agent with all user-available skills, Docker backend.
 * Creates or reuses a "Default Chat" graph from the default-chat template.
 */

import { graphTemplateService } from '@/app/workspace/[workspaceId]/[agentId]/services/graphTemplateService'
import { graphKeys } from '@/hooks/queries/graphs'
import { toastError, toastSuccess } from '@/lib/utils/toast'

import { MessageSquare } from 'lucide-react'

import { getModeConfig } from '../../config/modeConfig'
import { findGraphByName, refreshAndFindGraph } from '../utils/graphLookup'

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

let initPromise: Promise<ModeSelectionResult> | null = null

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
    if (initPromise) {
      return initPromise
    }

    initPromise = (async (): Promise<ModeSelectionResult> => {
      try {
        if (!context.personalWorkspaceId) {
          return {
            success: false,
            error: 'Personal workspace not found. Please ensure you have a personal workspace.',
          }
        }

        // Check if graph already exists
        const existing = await findGraphByName(TEMPLATE_GRAPH_NAME, context)
        if (existing) {
          return {
            success: true,
            stateUpdates: { mode: 'default-chat', graphId: existing.id },
          }
        }

        const modeConfig = getModeConfig('default-chat')
        if (!modeConfig?.templateName || !modeConfig.templateGraphName) {
          return {
            success: false,
            error: 'Default Chat template configuration not found',
          }
        }

        // Double-check after refresh (prevent race)
        const freshExisting = await refreshAndFindGraph(TEMPLATE_GRAPH_NAME, context)
        if (freshExisting) {
          return {
            success: true,
            stateUpdates: { mode: 'default-chat', graphId: freshExisting.id },
          }
        }

        // Create from template
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
          stateUpdates: { mode: 'default-chat', graphId: createdGraph.id },
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to create Default Chat graph'
        toastError(message, 'Graph Creation Failed')
        return { success: false, error: message }
      } finally {
        initPromise = null
      }
    })()

    return initPromise
  },

  async onSubmit(
    input: string,
    files: UploadedFile[],
    context: ModeContext
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

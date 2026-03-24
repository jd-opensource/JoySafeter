/**
 * Factory for template-based mode handlers.
 *
 * All "find-or-create a graph from a template" handlers share the same
 * onSelect / onSubmit / validate / getGraphId logic. Only the mode id,
 * graph display name, icon, and i18n keys differ.
 */

import { graphKeys } from '@/hooks/queries/graphs'

import { getModeConfig } from '../../config/modeConfig'
import { findGraphByName, findOrCreateGraphByTemplate } from '../utils/graphLookup'

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  UploadedFile,
  ModeMetadata,
} from './types'

interface TemplateHandlerConfig {
  modeId: string
  graphName: string // display name used in findGraphByName (e.g. "Default Chat")
  metadata: ModeMetadata
}

export function createTemplateHandler(cfg: TemplateHandlerConfig): ModeHandler {
  return {
    metadata: cfg.metadata,

    requiresFiles: false,

    async onSelect(context: ModeContext): Promise<ModeSelectionResult> {
      if (!context.personalWorkspaceId) {
        return {
          success: false,
          error: 'Personal workspace not found. Please ensure you have a personal workspace.',
        }
      }

      const modeConfig = getModeConfig(cfg.modeId)
      if (!modeConfig || !modeConfig.templateName || !modeConfig.templateGraphName) {
        return {
          success: false,
          error: `${cfg.graphName} template configuration not found`,
        }
      }

      try {
        const graph = await findOrCreateGraphByTemplate(
          modeConfig.templateGraphName,
          modeConfig.templateName,
          context.personalWorkspaceId,
        )

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
          stateUpdates: { mode: cfg.modeId, graphId: graph.id },
        }
      } catch (error) {
        const message =
          error instanceof Error ? error.message : `Failed to create ${cfg.graphName} graph`
        return { success: false, error: message }
      }
    },

    async onSubmit(
      input: string,
      _files: UploadedFile[],
      _context: ModeContext,
    ): Promise<SubmitResult> {
      return { success: true, processedInput: input }
    },

    validate(_input: string, _files: UploadedFile[]): ValidationResult {
      return { valid: true }
    },

    async getGraphId(context: ModeContext): Promise<string | null> {
      const graph = await findGraphByName(cfg.graphName, context)
      return graph?.id ?? null
    },
  }
}

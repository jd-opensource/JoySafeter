/**
 * Skill Creator Handler
 *
 * Handles skill creation mode — finds or creates a "Skill Creator" graph
 * from the skill-creator template, using the shared findOrCreateGraphByTemplate lock.
 */

import { Wand2 } from 'lucide-react'

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
} from './types'


const SKILL_CREATOR_GRAPH_NAME = 'Skill Creator'

/**
 * Skill Creator Mode Handler
 */
export const skillCreatorHandler: ModeHandler = {
  metadata: {
    id: 'skill-creator',
    label: 'chat.skillCreator',
    description: 'chat.skillCreatorDescription',
    icon: Wand2,
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

    const modeConfig = getModeConfig('skill-creator')
    if (!modeConfig || !modeConfig.templateName || !modeConfig.templateGraphName) {
      return {
        success: false,
        error: 'Skill Creator template configuration not found',
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
        stateUpdates: { mode: 'skill-creator', graphId: graph.id },
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Failed to create Skill Creator graph'
      return { success: false, error: errorMessage }
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
    const graph = await findGraphByName(SKILL_CREATOR_GRAPH_NAME, context)
    return graph?.id ?? null
  },
}

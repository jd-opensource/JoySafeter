/**
 * Skill Creator Handler
 *
 * Handles skill creation mode — finds or creates a "Skill Creator" graph
 * from the skill-creator template, following the same pattern as apkVulnerabilityHandler.
 */

import { graphTemplateService } from '@/app/workspace/[workspaceId]/[agentId]/services/graphTemplateService'
import { graphKeys } from '@/hooks/queries/graphs'
import { toastError, toastSuccess } from '@/lib/utils/toast'

import { getModeConfig } from '../../config/modeConfig'
import { findGraphByName, refreshAndFindGraph } from '../utils/graphLookup'

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  UploadedFile,
} from './types'

// Wand2 as icon placeholder — matches modeConfig
import { Wand2 } from 'lucide-react'

const SKILL_CREATOR_GRAPH_NAME = 'Skill Creator'

// Lock to prevent concurrent graph creation
let creatingGraphPromise: Promise<ModeSelectionResult> | null = null

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

    // Check if graph already exists
    const existing = await findGraphByName(SKILL_CREATOR_GRAPH_NAME, context)
    if (existing) {
      return {
        success: true,
        stateUpdates: { mode: 'skill-creator', graphId: existing.id },
      }
    }

    // If a creation is already in progress, wait for it
    if (creatingGraphPromise) {
      return creatingGraphPromise
    }

    const modeConfig = getModeConfig('skill-creator')
    if (!modeConfig || !modeConfig.templateName || !modeConfig.templateGraphName) {
      return {
        success: false,
        error: 'Skill Creator template configuration not found',
      }
    }

    creatingGraphPromise = (async (): Promise<ModeSelectionResult> => {
      try {
        // Double-check after refresh (prevent race)
        const freshExisting = await refreshAndFindGraph(SKILL_CREATOR_GRAPH_NAME, context)
        if (freshExisting) {
          return {
            success: true,
            stateUpdates: { mode: 'skill-creator', graphId: freshExisting.id },
          }
        }

        // Create from template
        const createdGraph = await graphTemplateService.createGraphFromTemplate(
          modeConfig.templateName!,
          modeConfig.templateGraphName!,
          context.personalWorkspaceId!
        )

        if (context.queryClient.refetchQueries) {
          await context.queryClient.refetchQueries({
            queryKey: [...graphKeys.list(context.personalWorkspaceId!)],
          })
        } else {
          context.queryClient.invalidateQueries({
            queryKey: [...graphKeys.list(context.personalWorkspaceId!)],
          })
        }

        toastSuccess('Skill Creator graph created successfully', 'Graph Initialized')

        return {
          success: true,
          stateUpdates: { mode: 'skill-creator', graphId: createdGraph.id },
        }
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : 'Failed to create Skill Creator graph'
        toastError(errorMessage, 'Graph Creation Failed')
        return { success: false, error: errorMessage }
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
    return { success: true, processedInput: input }
  },

  validate(input: string, files: UploadedFile[]): ValidationResult {
    return { valid: true }
  },

  async getGraphId(context: ModeContext): Promise<string | null> {
    const graph = await findGraphByName(SKILL_CREATOR_GRAPH_NAME, context)
    return graph?.id ?? null
  },
}

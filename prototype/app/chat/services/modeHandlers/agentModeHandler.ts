/**
 * Agent Mode Handler
 *
 * Handles agent selection mode
 * Used when user selects a deployed agent
 */

import { Bot } from 'lucide-react'

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  ModeMetadata,
} from './types'

/**
 * Agent Mode Handler
 *
 * This is a special handler for handling user selection of deployed agents
 */
export const agentModeHandler: ModeHandler = {
  metadata: {
    id: 'agent',
    label: 'Agent',
    description: 'Use deployed agent',
    icon: Bot,
    type: 'agent',
  },

  async onSelect(context: ModeContext): Promise<ModeSelectionResult> {
    const { selectedAgentId } = context

    if (!selectedAgentId) {
      return {
        success: false,
        error: 'No agent selected',
      }
    }

    // Find the corresponding agent
    const agent = context.deployedAgents.find((a) => a.id === selectedAgentId)
    if (!agent) {
      return {
        success: false,
        error: 'Selected agent not found',
      }
    }

    return {
      success: true,
      stateUpdates: {
        mode: 'agent',
        graphId: selectedAgentId,
      },
    }
  },

  async onSubmit(
    input: string,
    files: any[],
    context: ModeContext
  ): Promise<SubmitResult> {
    const { selectedAgentId } = context

    if (!selectedAgentId) {
      return {
        success: false,
        error: 'No agent selected',
      }
    }

    return {
      success: true,
      processedInput: input,
      graphId: selectedAgentId,
    }
  },

  validate(input: string, files: any[]): ValidationResult {
    return { valid: true }
  },

  async getGraphId(context: ModeContext): Promise<string | null> {
    return context.selectedAgentId || null
  },
}

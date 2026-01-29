/**
 * Graph Resolution Service
 *
 * Unified Graph ID resolution logic, resolves which Graph to use based on different strategies
 */

import { chatModeService } from './chatModeService'
import type { ModeContext } from './modeHandlers/types'

/**
 * Graph resolution result
 */
export interface GraphResolutionResult {
  /** Resolved Graph ID */
  graphId: string | null
  /** Resolution strategy */
  strategy: 'mode' | 'autoRedirect' | 'agentSelection' | 'none'
  /** Error message (if any) */
  error?: string
}

/**
 * Graph Resolution Service
 */
class GraphResolutionService {
  /**
   * Resolve Graph ID
   *
   * Resolves in the following priority order:
   * 1. Graph specified by mode (if mode has graphId)
   * 2. Auto Redirect strategy (create new Graph)
   * 3. Agent Selection strategy (use selected Agent)
   *
   * @param mode Mode ID
   * @param context Mode context
   * @param autoRedirect Whether auto redirect is enabled
   * @returns Graph resolution result
   */
  async resolve(
    mode: string | null,
    context: ModeContext,
    autoRedirect: boolean
  ): Promise<GraphResolutionResult> {
    // Strategy 1: Graph specified by mode
    if (mode) {
      const handler = chatModeService.getHandler(mode)
      if (handler) {
        const graphId = await handler.getGraphId?.(context)
        if (graphId) {
          return {
            graphId,
            strategy: 'mode',
          }
        }
      }
    }

    // Strategy 2: Auto Redirect (create new Graph)
    if (autoRedirect) {
      // This strategy is handled by CopilotRedirectService
      // Return null here to let caller know redirect is needed
      return {
        graphId: null,
        strategy: 'autoRedirect',
      }
    }

    // Strategy 3: Agent Selection
    if (context.selectedAgentId) {
      return {
        graphId: context.selectedAgentId,
        strategy: 'agentSelection',
      }
    }

    // No suitable Graph found
    return {
      graphId: null,
      strategy: 'none',
    }
  }

  /**
   * Get Graph ID from mode state
   *
   * @param modeType Mode type
   * @param modeGraphId Graph ID stored in mode
   * @param context Mode context
   * @returns Graph ID
   */
  async getGraphIdFromMode(
    modeType: string | null,
    modeGraphId: string | null | undefined,
    context: ModeContext
  ): Promise<string | null> {
    if (modeGraphId) {
      return modeGraphId
    }

    if (modeType) {
      const handler = chatModeService.getHandler(modeType)
      if (handler) {
        return (await handler.getGraphId?.(context)) || null
      }
    }

    return null
  }
}

// Export singleton instance
export const graphResolutionService = new GraphResolutionService()

/**
 * Chat Mode Service
 *
 * Encapsulates mode-related business logic, provides mode configuration management and query functionality
 */

import { modeHandlerRegistry } from './modeHandlers/registry'
import type { ModeHandler } from './modeHandlers/types'

/**
 * Chat Mode Service
 */
class ChatModeService {
  /**
   * Get all registered mode handlers
   */
  getAllHandlers(): ModeHandler[] {
    return modeHandlerRegistry.getAll()
  }

  /**
   * Get a mode handler
   *
   * @param modeId Mode ID
   * @returns Mode handler instance, or undefined if not found
   */
  getHandler(modeId: string): ModeHandler | undefined {
    return modeHandlerRegistry.get(modeId)
  }
}

// Export singleton instance
export const chatModeService = new ChatModeService()

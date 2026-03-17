/**
 * Chat Mode Service
 *
 * Encapsulates mode-related business logic, provides mode configuration management and query functionality
 */

import { modeHandlerRegistry } from './modeHandlers/registry'
import type { ModeHandler, ModeMetadata } from './modeHandlers/types'

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

  /**
   * Get metadata for all modes
   */
  getAllModeMetadata(): ModeMetadata[] {
    return this.getAllHandlers().map((handler) => handler.metadata)
  }

  /**
   * Get metadata for a mode
   *
   * @param modeId Mode ID
   * @returns Mode metadata, or undefined if not found
   */
  getModeMetadata(modeId: string): ModeMetadata | undefined {
    const handler = this.getHandler(modeId)
    return handler?.metadata
  }

  /**
   * Check if a mode exists
   *
   * @param modeId Mode ID
   * @returns Whether the mode exists
   */
  hasMode(modeId: string): boolean {
    return modeHandlerRegistry.has(modeId)
  }

  /**
   * Get all mode IDs
   */
  getAllModeIds(): string[] {
    return modeHandlerRegistry.getModeIds()
  }
}

// Export singleton instance
export const chatModeService = new ChatModeService()

/**
 * Mode Handler Registry
 *
 * Registry for mode handlers, used to manage and lookup different mode handlers
 */

import type { ModeHandler } from './types'

/**
 * Mode Handler Registry
 *
 * Uses singleton pattern to ensure only one registry instance globally
 */
class ModeHandlerRegistry {
  private handlers = new Map<string, ModeHandler>()

  /**
   * Register a mode handler
   *
   * @param modeId Mode ID
   * @param handler Mode handler instance
   */
  register(modeId: string, handler: ModeHandler): void {
    if (this.handlers.has(modeId)) {
      console.warn(`Mode handler for "${modeId}" is already registered. Overwriting...`)
    }
    this.handlers.set(modeId, handler)
  }

  /**
   * Get a mode handler
   *
   * @param modeId Mode ID
   * @returns Mode handler instance, or undefined if not found
   */
  get(modeId: string): ModeHandler | undefined {
    return this.handlers.get(modeId)
  }

  /**
   * Get all registered mode handlers
   *
   * @returns Array of all mode handlers
   */
  getAll(): ModeHandler[] {
    return Array.from(this.handlers.values())
  }

  /**
   * Check if a mode handler is registered
   *
   * @param modeId Mode ID
   * @returns Whether the handler is registered
   */
  has(modeId: string): boolean {
    return this.handlers.has(modeId)
  }

  /**
   * Get all registered mode IDs
   *
   * @returns Array of mode IDs
   */
  getModeIds(): string[] {
    return Array.from(this.handlers.keys())
  }

  /**
   * Clear all registered mode handlers
   */
  clear(): void {
    this.handlers.clear()
  }
}

// Export singleton instance
export const modeHandlerRegistry = new ModeHandlerRegistry()

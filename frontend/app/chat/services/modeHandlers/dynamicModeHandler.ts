/**
 * Dynamic Mode Handler
 *
 * Handles dynamic type modes (e.g., ctf)
 * These modes directly redirect to /dynamic/chat page
 */

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ModeMetadata,
} from './types'

/**
 * Create a Dynamic Mode Handler
 *
 * @param metadata Mode metadata
 * @returns ModeHandler instance
 */
export function createDynamicModeHandler(metadata: ModeMetadata): ModeHandler {
  return {
    metadata,

    async onSelect(context: ModeContext): Promise<ModeSelectionResult> {
      const { scene } = metadata

      if (!scene) {
        return {
          success: false,
          error: 'Dynamic mode requires a scene parameter',
        }
      }

      // Open dynamic chat page in a new window
      const path = `/dynamic/chat?scene=${scene}`
      window.open(path, '_blank')

      return {
        success: true,
      }
    },

    async onSubmit(
      input: string,
      files: any[],
      context: ModeContext
    ): Promise<SubmitResult> {
      // Dynamic modes should not be submitted through ChatHome
      // They should directly redirect to dynamic chat page
      return {
        success: false,
        error: 'Dynamic mode should be handled by redirecting to /dynamic/chat',
      }
    },

    validate(input: string, files: any[]) {
      return { valid: true }
    },
  }
}

// Note: These handlers are now created from config via handlerFactory
// Keeping these exports for backward compatibility, but recommend using createHandlerFromConfig

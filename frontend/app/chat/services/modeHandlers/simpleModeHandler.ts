/**
 * Simple Mode Handler
 *
 * Handles simple modes that only need to set the mode type, no special processing required
 */

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  ModeMetadata,
  UploadedFile,
} from './types'

/**
 * Create a simple mode handler
 *
 * @param metadata Mode metadata
 * @returns ModeHandler instance
 */
export function createSimpleModeHandler(metadata: ModeMetadata): ModeHandler {
  return {
    metadata,

    async onSelect(_context: ModeContext): Promise<ModeSelectionResult> {
      return {
        success: true,
        stateUpdates: {
          mode: metadata.id,
        },
      }
    },

    async onSubmit(input: string, _files: UploadedFile[], _context: ModeContext): Promise<SubmitResult> {
      return {
        success: true,
        processedInput: input,
        graphId: null,
      }
    },

    validate(_input: string, _files: UploadedFile[]): ValidationResult {
      return { valid: true }
    },
  }
}

// Note: These handlers are now created from config via handlerFactory
// Keeping these exports for backward compatibility, but recommend using createHandlerFromConfig

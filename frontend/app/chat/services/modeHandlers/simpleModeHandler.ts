/**
 * Simple Mode Handler
 *
 * Handles simple modes that only need to set the mode type, no special processing required
 */

import { Server } from 'lucide-react'

import type {
  ModeHandler,
  ModeContext,
  ModeSelectionResult,
  SubmitResult,
  ValidationResult,
  ModeMetadata,
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

    async onSelect(context: ModeContext): Promise<ModeSelectionResult> {
      return {
        success: true,
        stateUpdates: {
          mode: metadata.id,
        },
      }
    },

    async onSubmit(
      input: string,
      files: any[],
      context: ModeContext
    ): Promise<SubmitResult> {
      return {
        success: true,
        processedInput: input,
        graphId: null,
      }
    },

    validate(input: string, files: any[]): ValidationResult {
      return { valid: true }
    },
  }
}

// Note: These handlers are now created from config via handlerFactory
// Keeping these exports for backward compatibility, but recommend using createHandlerFromConfig

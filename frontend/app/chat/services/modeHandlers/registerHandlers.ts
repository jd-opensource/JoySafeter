/**
 * Register Mode Handlers
 * 
 * Registers all mode handlers
 * Creates and registers handlers from configuration uniformly to ensure consistency
 */

import { modeConfigs } from '../../config/modeConfig'

import { createHandlerFromConfig } from './handlerFactory'
import { modeHandlerRegistry } from './registry'

/**
 * Register all mode handlers
 * 
 * Creates handlers uniformly from modeConfigs to ensure consistency between config and handlers
 * 
 * Note: Special handlers (apk-vulnerability, agent) are already handled in handlerFactory,
 * no need to register them again here
 */
export function registerAllHandlers(): void {
  // Iterate through all configs, create and register handlers
  // handlerFactory will handle special handlers (apk-vulnerability, agent)
  for (const config of modeConfigs) {
    const handler = createHandlerFromConfig(config)
    if (handler) {
      modeHandlerRegistry.register(config.id, handler)
    } else {
      console.warn(`Failed to create handler for mode: ${config.id}`)
    }
  }
}


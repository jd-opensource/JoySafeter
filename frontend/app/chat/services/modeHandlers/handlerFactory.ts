/**
 * Mode Handler Factory
 *
 * Creates mode handlers from configuration, ensuring consistency between config and handlers
 */

import type { ModeConfig } from '../../config/modeConfig'

import { agentModeHandler } from './agentModeHandler'
import { apkVulnerabilityHandler } from './apkVulnerabilityHandler'
import { defaultChatModeHandler } from './defaultChatModeHandler'
import { createDynamicModeHandler } from './dynamicModeHandler'
import { createSimpleModeHandler } from './simpleModeHandler'
import type { ModeHandler, ModeMetadata } from './types'

/**
 * Create a mode handler from configuration
 *
 * @param config Mode configuration
 * @returns Mode handler instance, or null if creation fails
 */
export function createHandlerFromConfig(config: ModeConfig): ModeHandler | null {
  // Special handlers (have complex logic, cannot be created directly from config)
  if (config.id === 'default-chat') {
    return defaultChatModeHandler
  }

  if (config.id === 'apk-vulnerability') {
    return apkVulnerabilityHandler
  }

  if (config.id === 'agent') {
    return agentModeHandler
  }

  // Create metadata from config
  const metadata: ModeMetadata = {
    id: config.id,
    label: config.labelKey, // Note: stores the translation key, actual label needs translation
    description: config.descriptionKey, // Note: stores the translation key, actual description needs translation
    icon: config.icon,
    type: config.type,
    scene: config.scene,
    templateName: config.templateName,
    templateGraphName: config.templateGraphName,
  }

  // Create handler based on type
  if (config.type === 'dynamic') {
    return createDynamicModeHandler(metadata)
  }

  if (config.type === 'simple') {
    return createSimpleModeHandler(metadata)
  }

  return null
}

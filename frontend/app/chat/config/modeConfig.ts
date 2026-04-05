/**
 * Mode Configuration
 *
 * Mode configuration, defines all available chat modes and their metadata
 */

import React from 'react'

import { LucideIcon, Server, MessageSquare, Wand2 } from 'lucide-react'

import { AndroidIcon } from '../components/icons/AndroidIcon'

/**
 * Mode configuration type
 */
export interface ModeConfig {
  id: string
  labelKey: string
  descriptionKey: string
  icon: LucideIcon | React.ComponentType<{ className?: string }>
  type?: 'template' | 'simple' | 'agent'
  templateName?: string
  templateGraphName?: string
  starterPrompts?: string[]
}

/**
 * Mode configuration list
 *
 * This configuration is used for:
 * 1. Generating mode cards in UI
 * 2. Associating with mode handlers
 */
export const modeConfigs: ModeConfig[] = [
  {
    id: 'default-chat',
    labelKey: 'chat.defaultChat',
    descriptionKey: 'chat.defaultChatDescription',
    icon: MessageSquare,
    type: 'template',
    templateName: 'default-chat',
    templateGraphName: 'Default Chat',
  },
  {
    id: 'mcp-scan',
    labelKey: 'chat.mcpScan',
    descriptionKey: 'chat.mcpScanDescription',
    icon: Server,
    type: 'simple',
    starterPrompts: [
      'Scan my MCP service configuration',
      'Check if MCP permission settings are secure',
    ],
  },
  {
    id: 'apk-vulnerability',
    labelKey: 'chat.apkVulnerability',
    descriptionKey: 'chat.apkVulnerabilityDescription',
    icon: AndroidIcon,
    type: 'template',
    templateName: 'apk-detector',
    templateGraphName: 'APK Detector',
    starterPrompts: [
      'Upload APK for IntentBridge vulnerability detection',
      'Analyze APK component exposure risks',
    ],
  },
  {
    id: 'skill-creator',
    labelKey: 'chat.skillCreator',
    descriptionKey: 'chat.skillCreatorDescription',
    icon: Wand2,
    type: 'template',
    templateName: 'skill-creator',
    templateGraphName: 'Skill Creator',
    starterPrompts: [
      'Create a network scanning skill',
      'Help me design an automated penetration testing skill',
    ],
  },
]

/**
 * Get configuration by mode ID
 *
 * @param modeId Mode ID
 * @returns Mode configuration, or undefined if not found
 */
export function getModeConfig(modeId: string): ModeConfig | undefined {
  return modeConfigs.find((config) => config.id === modeId)
}

/**
 * Get all mode configurations
 */
export function getAllModeConfigs(): ModeConfig[] {
  return modeConfigs
}

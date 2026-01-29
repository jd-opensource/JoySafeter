/**
 * Mode Configuration
 * 
 * Mode configuration, defines all available chat modes and their metadata
 */

import { Flag, ShieldCheck, Code, Server } from 'lucide-react'

import { AndroidIcon } from '../components/icons/AndroidIcon'
import type { ModeMetadata } from '../services/modeHandlers/types'

/**
 * Mode configuration type
 */
export interface ModeConfig {
  id: string
  labelKey: string
  descriptionKey: string
  icon: any
  type?: 'dynamic' | 'template' | 'simple' | 'agent'
  scene?: string
  templateName?: string
  templateGraphName?: string
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
    id: 'ctf',
    labelKey: 'chat.ctf',
    descriptionKey: 'chat.ctfDescription',
    icon: Flag,
    type: 'dynamic',
    scene: 'ctf',
  },
  {
    id: 'enterprise-scan',
    labelKey: 'chat.enterpriseScan',
    descriptionKey: 'chat.enterpriseScanDescription',
    icon: ShieldCheck,
    type: 'dynamic',
    scene: 'pentest',
  },
  {
    id: 'whitebox-scanner',
    labelKey: 'chat.whiteboxScanner',
    descriptionKey: 'chat.whiteboxScannerDescription',
    icon: Code,
    type: 'dynamic',
    scene: 'whitebox',
  },
  {
    id: 'mcp-scan',
    labelKey: 'chat.mcpScan',
    descriptionKey: 'chat.mcpScanDescription',
    icon: Server,
    type: 'simple',
  },
  {
    id: 'apk-vulnerability',
    labelKey: 'chat.apkVulnerability',
    descriptionKey: 'chat.apkVulnerabilityDescription',
    icon: AndroidIcon,
    type: 'template',
    templateName: 'apk-detector',
    templateGraphName: 'APK Detector',
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


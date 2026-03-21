/**
 * Mode Configuration
 *
 * Mode configuration, defines all available chat modes and their metadata
 */

import { Server, MessageSquare, Wand2 } from 'lucide-react'

import { AndroidIcon } from '../components/icons/AndroidIcon'

/**
 * Mode configuration type
 */
export interface ModeConfig {
  id: string
  labelKey: string
  descriptionKey: string
  icon: any
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
    starterPrompts: [
      '帮我分析一段代码的安全性',
      '如何防范常见的Web漏洞？',
      '解释一下OWASP Top 10',
    ],
  },
  {
    id: 'mcp-scan',
    labelKey: 'chat.mcpScan',
    descriptionKey: 'chat.mcpScanDescription',
    icon: Server,
    type: 'simple',
    starterPrompts: [
      '扫描我的MCP服务配置',
      '检查MCP权限设置是否安全',
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
      '上传APK进行IntentBridge漏洞检测',
      '分析APK的组件暴露风险',
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
      '创建一个网络扫描技能',
      '帮我设计一个自动化渗透测试技能',
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

/**
 * Copilot Utility Functions
 * 
 * Shared utility functions for Copilot components
 */

import type { StageType } from '@/hooks/copilot/useCopilotStreaming'
import type { GraphAction } from '@/types/copilot'

/**
 * Format action content for display
 */
export function formatActionContent(action: GraphAction): string {
  const parts: string[] = []
  
  // Add action type
  parts.push(action.type)
  
  // Add payload details based on action type
  if (action.payload) {
    switch (action.type) {
      case 'CREATE_NODE':
        if (action.payload.label) parts.push(`创建节点: ${action.payload.label}`)
        if (action.payload.type) parts.push(`类型: ${action.payload.type}`)
        break
      case 'CONNECT_NODES':
        if (action.payload.source && action.payload.target) {
          parts.push(`连接: ${action.payload.source} → ${action.payload.target}`)
        }
        break
      case 'DELETE_NODE':
        if (action.payload.id) parts.push(`删除节点: ${action.payload.id}`)
        break
      case 'UPDATE_CONFIG':
        if (action.payload.id) parts.push(`更新配置: ${action.payload.id}`)
        break
      case 'UPDATE_POSITION':
        if (action.payload.id) parts.push(`更新位置: ${action.payload.id}`)
        break
    }
  }
  
  // Add reasoning if available
  if (action.reasoning) {
    parts.push(action.reasoning)
  }
  
  return parts.join(' • ')
}

/**
 * Check if there's a current message being streamed
 */
export function hasCurrentMessage(
  messages: Array<{ role: string; text?: string }>, 
  checkEmptyText = true
): boolean {
  if (messages.length === 0) return false
  const lastMessage = messages[messages.length - 1]
  if (lastMessage.role !== 'model') return false
  if (checkEmptyText && lastMessage.text) return false
  return true
}

/**
 * Get stage display configuration
 */
export function getStageConfig(
  t: (key: string, options?: { defaultValue?: string }) => string
): Record<StageType, { icon: string; color: string; label: string }> {
  return {
    thinking: { 
      icon: '💭', 
      color: 'text-purple-600', 
      label: t('copilot.stage.thinking', { defaultValue: '思考中' }) 
    },
    processing: { 
      icon: '✨', 
      color: 'text-green-600', 
      label: t('copilot.stage.processing', { defaultValue: '处理中' }) 
    },
    generating: { 
      icon: '🔧', 
      color: 'text-amber-600', 
      label: t('copilot.stage.generating', { defaultValue: '生成节点' }) 
    },
  }
}

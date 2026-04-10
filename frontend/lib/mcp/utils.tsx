/**
 * MCP utility functions
 * Provides reusable MCP-related utility functions
 */
import { CheckCircle2, XCircle, AlertCircle } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * MCP connection status type
 */
export type McpConnectionStatus = 'connected' | 'disconnected' | 'error'

/**
 * Get connection status icon
 */
export function getConnectionStatusIcon(status?: string): ReactNode {
  switch (status as McpConnectionStatus) {
    case 'connected':
      return <CheckCircle2 size={12} className="text-[var(--status-success)]" />
    case 'error':
      return <AlertCircle size={12} className="text-[var(--status-error)]" />
    default:
      return <XCircle size={12} className="text-[var(--text-muted)]" />
  }
}

/**
 * Get connection status text
 */
export function getConnectionStatusText(status?: string, t?: (key: string) => string): string {
  if (!t) {
    // If no translation function provided, return English default values
    switch (status as McpConnectionStatus) {
      case 'connected':
        return 'Connected'
      case 'error':
        return 'Error'
      default:
        return 'Disconnected'
    }
  }

  switch (status as McpConnectionStatus) {
    case 'connected':
      return t('settings.connected')
    case 'error':
      return t('settings.error')
    default:
      return t('settings.disconnected')
  }
}

/**
 * Get connection status style class
 */
export function getConnectionStatusClassName(status?: string): string {
  switch (status as McpConnectionStatus) {
    case 'connected':
      return 'text-[var(--status-success)] bg-[var(--status-success-bg)] border-[var(--status-success-border)]'
    case 'error':
      return 'text-[var(--status-error)] bg-[var(--status-error-bg)] border-[var(--status-error-border)]'
    default:
      return 'text-[var(--text-muted)] bg-[var(--surface-2)] border-[var(--border)]'
  }
}

/**
 * Format tool count text
 */
export function formatToolCount(count?: number, t?: (key: string) => string): string {
  const toolCount = count || 0
  if (!t) {
    // If no translation function provided, return English default values
    return `${toolCount} ${toolCount === 1 ? 'tool' : 'tools'}`
  }
  const toolText = toolCount === 1 ? t('settings.tool') : t('settings.tools')
  return `${toolCount} ${toolText}`
}

/**
 * Filter active and connected MCP servers
 */
export function filterActiveConnectedServers<
  T extends { enabled: boolean; connectionStatus?: string },
>(servers: T[]): T[] {
  return servers.filter((server) => server.enabled && server.connectionStatus === 'connected')
}

/**
 * Create MCP tool ID
 *
 * Use serverName as unique identifier
 */
export function createMcpToolId(serverName: string, toolName: string): string {
  return `${serverName}::${toolName}`
}

/**
 * Parse MCP tool ID
 *
 * Returns serverName and toolName
 */
export function parseMcpToolId(toolId: string): { serverName: string; toolName: string } | null {
  const parts = toolId.split('::')
  if (parts.length !== 2) {
    return null
  }
  return {
    serverName: parts[0],
    toolName: parts[1],
  }
}

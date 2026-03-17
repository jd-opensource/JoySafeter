/**
 * MCP Dialog utility functions
 * Provides reusable logic for MCP dialogs
 */
import type { McpServer } from '@/hooks/queries/mcp'

/**
 * MCP Server edit data interface
 */
export interface McpServerEditData {
  id: string
  name: string
  transport: string
  url?: string
  headers?: Record<string, string>
  timeout?: number
  enabled?: boolean
}

/**
 * Convert McpServer to edit data format
 */
export function serverToEditData(server: McpServer): McpServerEditData {
  return {
    id: server.id,
    name: server.name,
    transport: server.transport,
    url: server.url,
    headers: server.headers,
    timeout: server.timeout,
    enabled: server.enabled,
  }
}

/**
 * Default form configuration constants
 */
export const DEFAULT_MCP_FORM_CONFIG = {
  transport: 'streamable-http' as const,
  retries: 3,
  timeout: 30000,
  enabled: true,
} as const

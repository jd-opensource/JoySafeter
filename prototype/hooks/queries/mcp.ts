/**
 * MCP Server Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'

import { STALE_TIME } from './constants'

const logger = createLogger('McpQueries')

// ==================== Query Keys ====================

export const mcpKeys = {
  all: ['mcp'] as const,
  servers: () => [...mcpKeys.all, 'servers'] as const,
  tools: () => [...mcpKeys.all, 'tools'] as const,
}



// ==================== Types (camelCase) ====================

export interface McpServer {
  id: string
  name: string
  description?: string
  transport: 'streamable-http' | 'sse' | 'stdio'
  url?: string
  headers?: Record<string, string>
  timeout: number
  retries: number
  enabled: boolean
  connectionStatus?: 'connected' | 'disconnected' | 'error'
  lastConnected?: string
  lastError?: string
  toolCount?: number
  createdAt: string
  updatedAt: string
}

export interface McpServerConfig {
  name: string
  transport: 'streamable-http' | 'sse' | 'stdio'
  url?: string
  headers?: Record<string, string>
  timeout: number
  enabled: boolean
}

export interface McpTool {
  serverName: string
  name: string  // Real tool name (seen by LLM)
  labelName?: string  // Label name (for display, MCP tools are server_name::tool_name)
  description?: string
}

export interface McpTestResult {
  success: boolean
  error?: string
  tools?: Array<{ name: string; description?: string }>
  latencyMs?: number
}


// ==================== Query Hooks ====================

export function useMcpServers() {
  return useQuery({
    queryKey: mcpKeys.servers(),
    queryFn: async (): Promise<McpServer[]> => {
      const data = await apiGet<{ servers: McpServer[] }>('mcp/servers')
      return data.servers || []
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

export function useMcpToolsQuery() {
  return useQuery({
    queryKey: mcpKeys.tools(),
    queryFn: async (): Promise<McpTool[]> => {
      const data = await apiGet<{ tools: McpTool[] }>('mcp/tools')
      return data.tools || []
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}



// ==================== Mutation Hooks ====================

export function useCreateMcpServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ config }: { config: McpServerConfig }) => {
      const data = await apiPost<{ serverId: string }>('mcp/servers', config)

      logger.info(`Created MCP server: ${config.name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: mcpKeys.servers() })
      queryClient.invalidateQueries({ queryKey: mcpKeys.tools() })
    },
  })
}

export function useUpdateMcpServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ serverId, updates }: {
      serverId: string
      updates: Partial<McpServerConfig>
    }) => {
      const data = await apiPut<McpServer>(`mcp/servers/${serverId}`, updates)

      logger.info(`Updated MCP server: ${serverId}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: mcpKeys.servers() })
      queryClient.invalidateQueries({ queryKey: mcpKeys.tools() })
    },
  })
}

export function useDeleteMcpServer() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ serverId }: { serverId: string }) => {
      await apiDelete(`mcp/servers/${serverId}`)
      logger.info(`Deleted MCP server: ${serverId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: mcpKeys.servers() })
      queryClient.invalidateQueries({ queryKey: mcpKeys.tools() })
    },
  })
}

export function useTestMcpServer() {
  return useMutation({
    mutationFn: async (params: {
      transport: 'streamable-http' | 'sse' | 'stdio'
      url?: string
      headers?: Record<string, string>
      timeout: number
    }): Promise<McpTestResult> => {
      try {
        return await apiPost<McpTestResult>('mcp/test', params)
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : 'Connection test failed',
        }
      }
    },
  })
}


// ==================== Exports ====================

export type McpServerTestParams = Pick<McpServerConfig, 'transport' | 'url' | 'headers' | 'timeout'>
export type McpServerTestResult = McpTestResult

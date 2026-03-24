/**
 * Hook for MCP tools discovery and execution
 */
import { useQueryClient } from '@tanstack/react-query'
import type React from 'react'
import { useCallback, useMemo } from 'react'

import { McpIcon } from '@/components/icons'
import { mcpKeys, useMcpToolsQuery, type McpTool } from '@/hooks/queries/mcp'
import { createLogger } from '@/lib/logs/console/logger'
import { createMcpToolId } from '@/lib/mcp/utils'

const logger = createLogger('useMcpTools')

interface McpToolForUI {
  id: string
  name: string
  description?: string
  serverName: string
  type: 'mcp'
  bgColor: string
  icon: React.ComponentType<any>
}

export function useMcpTools() {
  const queryClient = useQueryClient()
  const { data: mcpToolsData = [], isLoading, error: queryError } = useMcpToolsQuery()

  const mcpTools = useMemo<McpToolForUI[]>(() => {
    return mcpToolsData.map((tool: McpTool) => {
      // Use labelName as ID (for management and display), if not available use serverName::name
      const labelName = tool.labelName || createMcpToolId(tool.serverName, tool.name)
      return {
        id: labelName, // Use labelName as identifier (server_name::tool_name)
        name: tool.name, // Real tool name (for display)
        description: tool.description,
        serverName: tool.serverName,
        type: 'mcp' as const,
        bgColor: '#6366F1',
        icon: McpIcon,
      }
    })
  }, [mcpToolsData])

  const refreshTools = useCallback(async () => {
    logger.info('Refreshing MCP tools')
    await queryClient.invalidateQueries({ queryKey: mcpKeys.tools() })
  }, [queryClient])

  const getToolById = useCallback(
    (toolId: string) => mcpTools.find((tool) => tool.id === toolId),
    [mcpTools],
  )

  const getToolsByServer = useCallback(
    (serverName: string) => mcpTools.filter((tool) => tool.serverName === serverName),
    [mcpTools],
  )

  return {
    mcpTools,
    isLoading,
    error: queryError instanceof Error ? queryError.message : null,
    refreshTools,
    getToolById,
    getToolsByServer,
  }
}


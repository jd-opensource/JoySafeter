/**
 * Tools Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { apiGet } from '@/lib/api-client'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const toolKeys = {
  all: ['tools'] as const,
  builtin: () => [...toolKeys.all, 'builtin'] as const,
}

// ==================== Types ====================

export interface BuiltinTool {
  id: string
  label: string
  name: string
  description?: string
  toolType: string
  category?: string | null
  tags?: string[]
  mcpServer?: string | null
}

// ==================== Query Hooks ====================

export function useBuiltinTools(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: toolKeys.builtin(),
    queryFn: async (): Promise<BuiltinTool[]> => {
      // apiGet automatically unwraps response.data, returns tool array directly
      const tools = await apiGet<Array<{
        id: string
        label: string
        name: string
        description?: string
        tool_type: string
        category?: string | null
        tags?: string[]
        mcp_server?: string | null
      }>>('tools/builtin')
      return (tools || []).map((tool) => ({
        id: tool.id,
        label: tool.label,
        name: tool.name,
        description: tool.description,
        toolType: tool.tool_type,
        category: tool.category ?? null,
        tags: tool.tags ?? [],
        mcpServer: tool.mcp_server ?? null,
      }))
    },
    enabled: options?.enabled !== false, // 默认 true，但可以设置为 false
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

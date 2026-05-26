/**
 * Custom Tools Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { apiGet } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'
import type { CustomToolDefinition, CustomToolSchema } from '@/stores/custom-tools/types'

const logger = createLogger('CustomToolsQueries')

/**
 * Query key factories for custom tools queries
 */
export const customToolsKeys = {
  all: ['customTools'] as const,
  lists: () => [...customToolsKeys.all, 'list'] as const,
  list: () => [...customToolsKeys.lists()] as const,
  detail: (toolId: string) => [...customToolsKeys.all, 'detail', toolId] as const,
}

type ApiCustomTool = Partial<CustomToolDefinition> & {
  id: string
  title: string
  schema: Partial<CustomToolSchema> & {
    function?: Partial<CustomToolSchema['function']> & {
      parameters?: Partial<NonNullable<CustomToolSchema['function']>['parameters']>
    }
  }
  code?: string
}

function normalizeCustomTool(tool: ApiCustomTool): CustomToolDefinition {
  const fallbackName = tool.schema.function?.name || tool.id
  const parameters = tool.schema.function?.parameters ?? {
    type: 'object',
    properties: {},
  }

  return {
    id: tool.id,
    title: tool.title,
    code: typeof tool.code === 'string' ? tool.code : '',
    userId: tool.userId ?? null,
    createdAt:
      typeof tool.createdAt === 'string'
        ? tool.createdAt
        : tool.updatedAt && typeof tool.updatedAt === 'string'
          ? tool.updatedAt
          : new Date().toISOString(),
    updatedAt: typeof tool.updatedAt === 'string' ? tool.updatedAt : undefined,
    schema: {
      type: tool.schema.type ?? 'function',
      function: {
        name: fallbackName,
        description: tool.schema.function?.description,
        parameters: {
          type: parameters.type ?? 'object',
          properties: parameters.properties ?? {},
          required: parameters.required,
        },
      },
    },
  }
}

// Raw API response type (backend may return name or title)
type RawApiCustomTool = Partial<CustomToolDefinition> & {
  id: string
  name?: string // Backend may return name
  title?: string
  schema?: any
  code?: string
  ownerId?: string // Backend may return ownerId instead of userId
  userId?: string | null
  createdAt?: string
  updatedAt?: string
}

/**
 * Fetch custom tools for the current user
 */
async function fetchCustomTools(): Promise<CustomToolDefinition[]> {
  const data = await apiGet<RawApiCustomTool[]>('custom-tools')

  if (!Array.isArray(data)) {
    throw new Error('Invalid response format')
  }

  const normalizedTools: CustomToolDefinition[] = []

  data.forEach((tool, index) => {
    if (!tool || typeof tool !== 'object') {
      logger.warn(`Skipping invalid tool at index ${index}: not an object`)
      return
    }
    if (!tool.id || typeof tool.id !== 'string') {
      logger.warn(`Skipping invalid tool at index ${index}: missing or invalid id`)
      return
    }
    // Backend returns 'name' but frontend expects 'title'
    const toolName = tool.name || tool.title
    if (!toolName || typeof toolName !== 'string') {
      logger.warn(`Skipping invalid tool at index ${index}: missing or invalid name/title`)
      return
    }
    if (!tool.schema || typeof tool.schema !== 'object') {
      logger.warn(`Skipping invalid tool at index ${index}: missing or invalid schema`)
      return
    }
    if (!tool.schema.function || typeof tool.schema.function !== 'object') {
      logger.warn(`Skipping invalid tool at index ${index}: missing function schema`)
      return
    }

    const apiTool: ApiCustomTool = {
      id: tool.id,
      title: toolName, // Use 'name' from backend as 'title' for frontend
      schema: tool.schema,
      code: typeof tool.code === 'string' ? tool.code : '',
      userId: tool.ownerId || tool.userId || null,
      createdAt: tool.createdAt ?? undefined,
      updatedAt: tool.updatedAt ?? undefined,
    }

    try {
      normalizedTools.push(normalizeCustomTool(apiTool))
    } catch (error) {
      logger.warn(`Failed to normalize custom tool at index ${index}`, { error })
    }
  })

  return normalizedTools
}

/**
 * Custom Tools Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { apiGet } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'
import { useCustomToolsStore } from '@/stores/custom-tools/store'
import type {
  CustomToolDefinition,
  CustomToolSchema,
  CustomTool as LegacyCustomTool,
  LegacyCustomToolSchema,
  CustomToolParameter,
} from '@/stores/custom-tools/types'


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

// Re-export CustomToolDefinition as CustomTool for backward compatibility
export type CustomTool = CustomToolDefinition

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

/**
 * Convert CustomToolDefinition (OpenAI format) to CustomTool (legacy format) for store
 */
function convertToLegacyTool(definition: CustomToolDefinition): LegacyCustomTool {
  const functionSchema = definition.schema.function
  const name = functionSchema?.name || definition.title
  const description = functionSchema?.description || ''

  // Convert OpenAI-style parameters to legacy format
  const parameters: CustomToolParameter[] = []
  if (functionSchema?.parameters?.properties) {
    const required = new Set(functionSchema.parameters.required || [])
    for (const [paramName, paramDef] of Object.entries(functionSchema.parameters.properties)) {
      if (typeof paramDef === 'object' && paramDef !== null) {
        parameters.push({
          name: paramName,
          type: (paramDef as any).type || 'string',
          description: (paramDef as any).description,
          required: required.has(paramName),
          default: (paramDef as any).default,
        })
      }
    }
  }

  const legacySchema: LegacyCustomToolSchema = {
    id: definition.id,
    name,
    description,
    parameters,
    code: definition.code,
  }

  return {
    id: definition.id,
    name,
    description,
    schema: legacySchema,
    createdAt: new Date(definition.createdAt),
    updatedAt: definition.updatedAt ? new Date(definition.updatedAt) : new Date(),
    userId: definition.userId || undefined,
  }
}

function syncCustomToolsToStore(tools: CustomToolDefinition[]) {
  const legacyTools = tools.map(convertToLegacyTool)
  useCustomToolsStore.getState().setTools(legacyTools)
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

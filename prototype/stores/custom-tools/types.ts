/**
 * Custom tools types
 */

export interface CustomToolParameter {
  name: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array'
  description?: string
  required?: boolean
  default?: unknown
}

// OpenAI-style function calling schema (used by custom-tools.ts)
// OpenAI-style function calling schema (used by custom-tools.ts queries)
export interface CustomToolSchema {
  type?: 'function'
  function?: {
    name: string
    description?: string
    parameters?: {
      type: 'object'
      properties?: Record<string, any>
      required?: string[]
    }
  }
}

// Legacy schema format (used by store)
export interface LegacyCustomToolSchema {
  id: string
  name: string
  description: string
  parameters: CustomToolParameter[]
  code?: string
  endpoint?: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
}

// CustomToolDefinition - used by API queries (OpenAI function calling format)
export interface CustomToolDefinition {
  id: string
  title: string
  code: string
  userId: string | null
  createdAt: string
  updatedAt?: string
  schema: CustomToolSchema
}

// Legacy CustomTool format (used by store)
export interface CustomTool {
  id: string
  name: string
  description: string
  schema: LegacyCustomToolSchema
  createdAt: Date
  updatedAt: Date
  userId?: string
}

export interface CustomToolsState {
  tools: Record<string, CustomTool>
  isLoading: boolean
  error: string | null
}

export interface CustomToolsActions {
  setTools: (tools: CustomTool[]) => void
  addTool: (tool: CustomTool) => void
  updateTool: (id: string, updates: Partial<CustomTool>) => void
  removeTool: (id: string) => void
  getTool: (id: string) => CustomTool | undefined
  getToolAsync: (id: string) => Promise<CustomTool | undefined>
  getAllTools: () => CustomTool[]
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
}

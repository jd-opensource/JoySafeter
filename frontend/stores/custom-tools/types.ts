/**
 * Custom tools types
 */

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

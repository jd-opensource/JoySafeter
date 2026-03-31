/**
 * Shared JSON Schema parser for model settings forms.
 * Used by credential-dialog, add-custom-model-dialog, and param-drawer.
 */

export interface SchemaField {
  key: string
  title: string
  description?: string
  type: string
  required: boolean
  enum?: string[]
  enumNames?: string[]
  default?: number | string | null
  minimum?: number
  maximum?: number
}

/**
 * Parse a JSON Schema object into a flat list of form fields.
 * Handles both credential schemas and config schemas.
 *
 * Expected input shape: { type: "object", properties: { fieldName: { title, type, ... } }, required: [...] }
 */
export function parseJsonSchema(schema: Record<string, any> | null | undefined): SchemaField[] {
  if (!schema || typeof schema !== 'object') return []

  // Navigate into { type: "object", properties: { ... } } wrapper
  const properties =
    schema.properties && typeof schema.properties === 'object'
      ? (schema.properties as Record<string, any>)
      : null

  if (!properties) return []

  const requiredFields: string[] = Array.isArray(schema.required) ? schema.required : []

  return Object.entries(properties).map(([key, prop]) => ({
    key,
    title: prop.title || key,
    description: prop.description,
    type: prop.type || 'string',
    required: requiredFields.includes(key) || prop.required === true,
    enum: prop.enum,
    enumNames: prop.enumNames,
    default: prop.default,
    minimum: prop.minimum,
    maximum: prop.maximum,
  }))
}

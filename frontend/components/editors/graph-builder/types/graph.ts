/**
 * Graph Types - Type definitions for DeepAgents canvas
 */

/**
 * Edge data structure stored in Edge.data
 */
export interface EdgeData {
  /** Edge type: normal or conditional */
  edge_type?: 'normal' | 'conditional'

  /** Display label for the edge */
  label?: string

  /** Route key for conditional routing */
  route_key?: string

  /** React Flow Handle ID */
  source_handle_id?: string
}

/**
 * Validation error for graph structure
 */
export interface ValidationError {
  field: string
  message: string
  severity?: 'error' | 'warning'
  nodeId?: string
  category?: string
}

/**
 * State field definition for graph variables
 */
export type StateFieldType = 'string' | 'int' | 'float' | 'bool' | 'list' | 'dict' | 'messages'
export type ReducerType = 'add' | 'append' | 'merge'

export interface StateField {
  name: string
  type: StateFieldType
  description?: string
  reducer?: ReducerType
  defaultValue?: unknown
  isSystem?: boolean
}

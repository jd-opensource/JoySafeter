/**
 * Graph Types - Unified type definitions for graph nodes and edges
 *
 * This file provides type-safe interfaces for graph data structures,
 * ensuring consistency between frontend and backend.
 */

import { Node, Edge } from 'reactflow'

/**
 * Edge data structure stored in Edge.data
 * This matches the backend GraphEdge.data JSONB field
 */
export interface EdgeData {
  /** Route key for conditional routing (matches RouterNodeExecutor return value) */
  route_key?: string

  /** React Flow Handle ID (e.g., "Yes", "No", "Unknown") */
  source_handle_id?: string

  /** Edge type: normal, conditional, or loop_back */
  edge_type?: 'normal' | 'conditional' | 'loop_back'

  /** Display label for the edge */
  label?: string


  /** Path waypoints for loop_back edges (stored as array of {x, y} in flow coordinates) */
  waypoints?: Array<{ x: number; y: number }>

  /** Vertical offset for loop_back edges horizontal channel (in flow coordinates) */
  offsetY?: number

  /** Horizontal offset for left vertical segment (in flow coordinates) */
  leftOffsetX?: number

  /** Horizontal offset for right vertical segment (in flow coordinates) */
  rightOffsetX?: number
}

/**
 * Route rule for Router nodes
 * Defines a condition and target edge mapping
 */
export interface RouteRule {
  /** Unique identifier for the rule */
  id: string

  /** Python expression that evaluates to boolean */
  condition: string

  /** Route key that matches the target edge's route_key */
  targetEdgeKey: string

  /** Display label for the route (e.g., "High Score", "Default") */
  label: string

  /** Priority/order for rule evaluation (lower = higher priority) */
  priority?: number
}

/**
 * Router node configuration
 */
export interface RouterNodeConfig {
  /** List of routing rules (evaluated in priority order) */
  routes: RouteRule[]

  /** Default route key when no conditions match */
  defaultRoute: string
}

/**
 * Loop Condition node configuration
 */
export interface LoopConditionNodeConfig {
  /** Loop type: forEach, while, or doWhile */
  conditionType?: 'forEach' | 'while' | 'doWhile'

  /** For forEach: state key containing the list to iterate */
  listVariable?: string

  /** For while/doWhile: Python expression returning boolean */
  condition?: string

  /** Maximum number of iterations (safety limit) */
  maxIterations?: number
}

/**
 * Condition node configuration
 */
export interface ConditionNodeConfig {
  /** Python expression that evaluates to True or False */
  expression: string

  /** Label for the True branch */
  trueLabel?: string

  /** Label for the False branch */
  falseLabel?: string
}

/**
 * Extended Edge type with typed data
 */
export type TypedEdge = Edge & {
  data?: EdgeData
}

/**
 * Extended Node type with typed data
 */
export type TypedNode = Node & {
  data: {
    type: string
    label?: string
    config?: Record<string, unknown>
  }
}

/**
 * Validation error structure
 */
export interface ValidationError {
  /** Field path (e.g., "routes[0].condition") */
  field: string

  /** Error message */
  message: string

  /** Optional severity level */
  severity?: 'error' | 'warning' | 'info'

  /** Optional node ID associated with the error */
  nodeId?: string

  /** Optional edge ID associated with the error */
  edgeId?: string

  /** Error category (e.g. "Node Configuration", "Graph Structure") */
  category?: string

  /** Whether the error can be automatically fixed */
  canAutoFix?: boolean
}

/**
 * State Field Data Types matching backend StateFieldType
 */
export type StateFieldType = 'string' | 'int' | 'float' | 'bool' | 'list' | 'dict' | 'messages' | 'any'

/**
 * State Field Reducer Types matching backend ReducerType
 */
export type ReducerType = 'replace' | 'add' | 'append' | 'merge' | 'add_messages' | 'custom'

/**
 * State Field Definition
 * Matches backend StateFieldSchema
 */
export interface StateField {
  name: string
  type: StateFieldType
  description?: string
  defaultValue?: any // Renamed from default to avoid keyword conflict if needed, or map to default in serialization
  reducer?: ReducerType
  required?: boolean
  isSystem?: boolean // Frontend-only flag to prevent editing system fields if we pre-populate them
}

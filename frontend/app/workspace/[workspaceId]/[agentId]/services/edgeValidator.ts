/**
 * Edge Validator - Validates edge data consistency and routing rules
 *
 * Provides validation for:
 * - Route rule to edge matching
 * - Edge type consistency
 * - Data completeness
 */

import { Node, Edge } from 'reactflow'

import { EdgeData, RouteRule, ValidationError } from '../types/graph'

/**
 * Validate that a route rule's targetEdgeKey matches an edge's route_key
 */
export function validateRouteRuleEdgeMatch(
  rule: RouteRule,
  edges: Edge[],
  sourceNodeId: string
): ValidationError[] {
  const errors: ValidationError[] = []

  // Find edges from the source node
  const outgoingEdges = edges.filter((e) => e.source === sourceNodeId)

  // Check if there's an edge with matching route_key
  const matchingEdge = outgoingEdges.find(
    (e) => (e.data as EdgeData)?.route_key === rule.targetEdgeKey
  )

  if (!matchingEdge && rule.targetEdgeKey) {
    errors.push({
      field: `route.${rule.id}.targetEdgeKey`,
      message: `No edge found with route_key "${rule.targetEdgeKey}". Please create an edge or update the route key.`,
      severity: 'error',
    })
  }

  // Check for duplicate route keys
  const duplicateEdges = outgoingEdges.filter(
    (e) => (e.data as EdgeData)?.route_key === rule.targetEdgeKey
  )
  if (duplicateEdges.length > 1) {
    errors.push({
      field: `route.${rule.id}.targetEdgeKey`,
      message: `Multiple edges found with route_key "${rule.targetEdgeKey}". Each route key should be unique.`,
      severity: 'warning',
    })
  }

  return errors
}

/**
 * Validate edge data completeness and consistency
 */
export function validateEdgeData(
  edge: Edge,
  sourceNode: Node | undefined,
  targetNode: Node | undefined
): ValidationError[] {
  const errors: ValidationError[] = []
  const edgeData = (edge.data || {}) as EdgeData
  const sourceNodeType = (sourceNode?.data as { type?: string })?.type || ''

  // Validate edge_type
  if (edgeData.edge_type) {
    const validTypes = ['normal', 'conditional', 'loop_back']
    if (!validTypes.includes(edgeData.edge_type)) {
      errors.push({
        field: 'edge_type',
        message: `Invalid edge_type: ${edgeData.edge_type}. Must be one of: ${validTypes.join(', ')}`,
        severity: 'error',
      })
    }
  }

  // Validate conditional edges from router/condition nodes
  const isConditionalSource = ['router_node', 'condition', 'loop_condition_node'].includes(
    sourceNodeType
  )

  if (isConditionalSource) {
    if (edgeData.edge_type === 'conditional' && !edgeData.route_key) {
      errors.push({
        field: 'route_key',
        message: 'Conditional edges from router/condition nodes must have a route_key',
        severity: 'error',
      })
    }
  }

  // Validate route_key format (should be alphanumeric with underscores)
  if (edgeData.route_key) {
    const routeKeyPattern = /^[a-zA-Z0-9_]+$/
    if (!routeKeyPattern.test(edgeData.route_key)) {
      errors.push({
        field: 'route_key',
        message: 'route_key must contain only letters, numbers, and underscores',
        severity: 'error',
      })
    }
  }

  // Validate source_handle_id for conditional edges
  if (edgeData.edge_type === 'conditional' && !edgeData.source_handle_id) {
    errors.push({
      field: 'source_handle_id',
      message: 'Conditional edges should have a source_handle_id',
      severity: 'warning',
    })
  }

  return errors
}

/**
 * Validate router node route-to-edge consistency
 * This focuses only on edge connectivity, not route configuration
 */
export function validateRouterNodeRoutes(
  routes: RouteRule[],
  edges: Edge[],
  sourceNodeId: string
): ValidationError[] {
  const errors: ValidationError[] = []

  if (!Array.isArray(routes)) {
    return errors // Let unified validator handle this
  }

  // Only validate route-to-edge connectivity (not route config itself)
  routes.forEach((rule) => {
    if (rule.targetEdgeKey) {
      const ruleErrors = validateRouteRuleEdgeMatch(rule, edges, sourceNodeId)
      errors.push(...ruleErrors)
    }
  })

  return errors
}

/**
 * Validate graph consistency (all nodes and edges)
 */
export function validateGraphConsistency(
  nodes: Node[],
  edges: Edge[]
): ValidationError[] {
  const errors: ValidationError[] = []

  // Validate each edge
  edges.forEach((edge) => {
    const sourceNode = nodes.find((n) => n.id === edge.source)
    const targetNode = nodes.find((n) => n.id === edge.target)

    if (!sourceNode) {
      errors.push({
        field: `edge.${edge.id}.source`,
        message: `Source node not found: ${edge.source}`,
        severity: 'error',
      })
    }

    if (!targetNode) {
      errors.push({
        field: `edge.${edge.id}.target`,
        message: `Target node not found: ${edge.target}`,
        severity: 'error',
      })
    }

    const edgeErrors = validateEdgeData(edge, sourceNode, targetNode)
    errors.push(...edgeErrors)
  })

    // Validate router nodes - only check route-to-edge connectivity
    // Node configuration validation is handled by unified validator
    nodes.forEach((node) => {
      const nodeType = (node.data as { type?: string })?.type
      const config = (node.data as { config?: Record<string, unknown> })?.config || {}

      if (nodeType === 'router_node') {
        const routes = config.routes as RouteRule[] | undefined
        if (routes) {
          const routeErrors = validateRouterNodeRoutes(routes, edges, node.id)
          errors.push(...routeErrors)
        }
      }
    })

  return errors
}

/**
 * Get validation errors for a specific field path
 */
export function getErrorsForField(
  errors: ValidationError[],
  fieldPath: string
): ValidationError[] {
  return errors.filter((error) => error.field === fieldPath || error.field.startsWith(fieldPath + '.'))
}

/**
 * Check if there are any critical errors (severity === 'error')
 */
export function hasCriticalErrors(errors: ValidationError[]): boolean {
  return errors.some((error) => error.severity === 'error')
}

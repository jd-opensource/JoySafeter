/**
 * Variable Service - API client for variable analysis and validation.
 */

import { apiGet, apiPost } from '@/lib/api-client'

export interface VariableInfo {
  name: string
  path: string
  source: string
  source_node_id?: string
  scope: 'global' | 'loop' | 'task' | 'node'
  description?: string
  value_type?: string
  is_defined: boolean
  is_used: boolean
  usages?: Array<{
    node_id: string
    node_label: string
    usage_type: string
  }>
}

export interface VariableValidationResult {
  valid: boolean
  errors: Array<{
    variable_name: string
    variable_path: string
    error_message: string
    suggestion?: string
  }>
  variables: Array<{
    name: string
    path: string
    available: boolean
  }>
}

/**
 * Get all variables in a graph.
 */
export async function getGraphVariables(graphId: string): Promise<VariableInfo[]> {
  // Note: This endpoint uses /graph/ instead of /v1/graphs/
  const response = await apiGet<{ variables: VariableInfo[] }>(`/graph/${graphId}/variables`)
  return response.variables || []
}

/**
 * Check if a string is a valid UUID format
 */
function isValidUUID(str: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  return uuidRegex.test(str)
}

/**
 * Get available variables for a specific node.
 *
 * Note: Only calls API if nodeId is a valid UUID (i.e., node is saved to database).
 * For temporary nodes (e.g., "node_xxx"), returns empty array and caller should use frontend fallback.
 */
export async function getNodeAvailableVariables(
  graphId: string,
  nodeId: string
): Promise<VariableInfo[]> {
  // Only call API if nodeId is a valid UUID (saved node)
  // Temporary nodes (e.g., "node_xxx") should use frontend fallback
  if (!isValidUUID(nodeId)) {
    // Return empty array for temporary nodes - caller should use frontend fallback
    return []
  }

  try {
    // Note: This endpoint uses /graph/ instead of /v1/graphs/
    const response = await apiGet<{ variables: VariableInfo[] }>(`/graph/${graphId}/nodes/${nodeId}/available-variables`)
    return response.variables || []
  } catch (error) {
    // If API call fails, return empty array - caller should use frontend fallback
    console.warn(`Failed to fetch variables for node ${nodeId}:`, error)
    return []
  }
}

/**
 * Validate variable usage in an expression.
 *
 * Note: Only calls API if nodeId is a valid UUID (i.e., node is saved to database).
 * For temporary nodes, returns a basic validation result.
 */
export async function validateVariableUsage(
  graphId: string,
  nodeId: string,
  expression: string
): Promise<VariableValidationResult> {
  // Only call API if nodeId is a valid UUID (saved node)
  if (!isValidUUID(nodeId)) {
    // For temporary nodes, return basic validation result
    return {
      valid: true,
      errors: [],
      variables: [],
    }
  }

  try {
    // Note: This endpoint uses /graph/ instead of /v1/graphs/
    const response = await apiPost<VariableValidationResult>(`/graph/${graphId}/validate-variables`, {
      node_id: nodeId,
      expression,
    })
    return response
  } catch (error) {
    // If API call fails, return basic validation result
    console.warn(`Failed to validate variables for node ${nodeId}:`, error)
    return {
      valid: true,
      errors: [],
      variables: [],
    }
  }
}

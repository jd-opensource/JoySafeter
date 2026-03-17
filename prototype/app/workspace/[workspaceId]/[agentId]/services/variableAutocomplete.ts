/**
 * Variable Autocomplete - Provides variable suggestions for input fields.
 *
 * Integrates with StateVariablePanel to provide autocomplete suggestions
 * when users are typing expressions or variable references.
 */

import { Node, Edge } from 'reactflow'

export interface VariableSuggestion {
  name: string
  path: string
  description?: string
  value_type?: string
  scope: string
  source: string
}

/**
 * Get variable suggestions for a given node.
 *
 * This analyzes the graph structure to determine which variables
 * are available at a specific node.
 */
export function getVariableSuggestions(
  nodes: Node[],
  edges: Edge[],
  currentNodeId: string
): VariableSuggestion[] {
  const suggestions: VariableSuggestion[] = []

  // System variables (always available)
  suggestions.push({
    name: 'current_node',
    path: 'state.current_node',
    description: 'Current executing node ID',
    value_type: 'string',
    scope: 'global',
    source: 'System',
  })

  suggestions.push({
    name: 'route_decision',
    path: 'state.route_decision',
    description: 'Latest route decision',
    value_type: 'string',
    scope: 'global',
    source: 'System',
  })

  suggestions.push({
    name: 'loop_count',
    path: 'state.loop_count',
    description: 'Global loop count',
    value_type: 'number',
    scope: 'global',
    source: 'System',
  })

  // Get upstream nodes
  const upstreamNodes = getUpstreamNodes(currentNodeId, nodes, edges)

  // Collect variables from upstream nodes
  upstreamNodes.forEach((node) => {
    const nodeData = node.data as { type?: string; label?: string; config?: Record<string, unknown> }
    const nodeType = nodeData.type || 'agent'
    const nodeLabel = nodeData.label || node.id
    const config = nodeData.config || {}

    // Add node-specific variables based on type
    if (nodeType === 'loop_condition_node') {
      suggestions.push({
        name: `loop_count_${node.id}`,
        path: `loop_states.${node.id}.loop_count`,
        description: `Loop count for '${nodeLabel}'`,
        value_type: 'number',
        scope: 'loop',
        source: nodeLabel,
      })
    }

    // Extract variables from node outputs (if any)
    // This would require analyzing node execution results
    // For now, we add common context variables
    if (nodeType === 'agent') {
      // These nodes typically output to context
      // We can't know exact variable names without execution,
      // but we can suggest common patterns
    }
  })

  return suggestions
}

/**
 * Get upstream nodes for a given node.
 */
function getUpstreamNodes(
  nodeId: string,
  nodes: Node[],
  edges: Edge[]
): Node[] {
  const upstream: Node[] = []
  const visited = new Set<string>()

  function traverse(currentNodeId: string) {
    if (visited.has(currentNodeId)) return
    visited.add(currentNodeId)

    edges.forEach((edge) => {
      if (edge.target === currentNodeId) {
        const sourceNode = nodes.find((n) => n.id === edge.source)
        if (sourceNode) {
          upstream.push(sourceNode)
          traverse(sourceNode.id)
        }
      }
    })
  }

  traverse(nodeId)
  return upstream
}

/**
 * Extract variable references from an expression.
 *
 * Used for validation and highlighting.
 */
export function extractVariableReferences(expression: string): string[] {
  const variables: string[] = []
  const patterns = [
    /state\.get\(['"]([^'"]+)['"]/g,
    /context\.get\(['"]([^'"]+)['"]/g,
    /state\[['"]([^'"]+)['"]/g,
    /context\[['"]([^'"]+)['"]/g,
    /\{\{(\w+)\}\}/g, // Template variables
  ]

  patterns.forEach((pattern) => {
    let match
    while ((match = pattern.exec(expression)) !== null) {
      variables.push(match[1])
    }
  })

  return [...new Set(variables)]
}

/**
 * Validate variable references in an expression.
 *
 * Returns errors for undefined variables.
 */
export function validateVariableReferences(
  expression: string,
  availableVariables: VariableSuggestion[]
): Array<{ variable: string; error: string }> {
  const errors: Array<{ variable: string; error: string }> = []
  const referencedVars = extractVariableReferences(expression)
  const availableVarNames = new Set(availableVariables.map((v) => v.name))
  const availableVarPaths = new Set(availableVariables.map((v) => v.path))

  referencedVars.forEach((varName) => {
    // Check if variable name is available
    if (!availableVarNames.has(varName)) {
      // Check if it's a path-based reference
      const pathMatches = Array.from(availableVarPaths).filter((path) =>
        path.includes(varName)
      )
      if (pathMatches.length === 0) {
        errors.push({
          variable: varName,
          error: `Variable '${varName}' is not available in this context`,
        })
      }
    }
  })

  return errors
}

/**
 * Generate autocomplete suggestions based on current input.
 */
export function getAutocompleteSuggestions(
  input: string,
  cursorPosition: number,
  availableVariables: VariableSuggestion[]
): VariableSuggestion[] {
  // Extract the word being typed
  const beforeCursor = input.substring(0, cursorPosition)
  const match = beforeCursor.match(/(\w+)$/)
  const prefix = match ? match[1] : ''

  if (!prefix) {
    return availableVariables.slice(0, 10) // Return first 10 if no prefix
  }

  // Filter variables that match the prefix
  return availableVariables
    .filter(
      (v) =>
        v.name.toLowerCase().startsWith(prefix.toLowerCase()) ||
        v.path.toLowerCase().includes(prefix.toLowerCase())
    )
    .slice(0, 10)
}

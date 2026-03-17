/**
 * Node Name Utilities - Unified node name conversion utilities
 *
 * Ensures frontend-generated node names are consistent with backend LangGraph names.
 * Backend name generation logic from: backend/app/core/graph/base_builder.py::_get_node_name
 */

/**
 * Convert node label and ID to LangGraph node name
 *
 * Backend format: `{label.lower().replace(" ", "_").replace("-", "_")}_{node.id[:8]}`
 *
 * @param label - Node display label
 * @param nodeId - Node unique ID
 * @param nodeType - Node type (used for fallback)
 * @returns Node name in LangGraph format
 *
 * @example
 * toLangGraphNodeName("My Agent", "abc12345-def6-7890") // returns "my_agent_abc12345"
 * toLangGraphNodeName("", "abc12345-def6-7890", "agent") // returns "agent_abc12345"
 */
export function toLangGraphNodeName(
  label: string | undefined,
  nodeId: string,
  nodeType: string = 'agent'
): string {
  // Get first 8 characters of node ID
  const shortId = nodeId.slice(0, 8)

  if (label && label.trim()) {
    // Transform label: lowercase, replace spaces and hyphens with underscores
    const sanitizedLabel = label
      .toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/-+/g, '_')
    return `${sanitizedLabel}_${shortId}`
  }

  // If no label, use node type
  return `${nodeType}_${shortId}`
}

/**
 * Extract LangGraph node name from React Flow node object
 *
 * @param node - React Flow node object
 * @returns Node name in LangGraph format
 */
export function getNodeNameFromFlowNode(node: {
  id: string
  data?: {
    label?: string
    type?: string
  }
}): string {
  const label = node.data?.label
  const nodeType = node.data?.type || 'agent'
  return toLangGraphNodeName(label, node.id, nodeType)
}

/**
 * Validate if a node name is a valid LangGraph node name
 *
 * @param name - Name to validate
 * @returns Whether the name is a valid node name
 */
export function isValidLangGraphNodeName(name: string): boolean {
  // LangGraph node names should only contain lowercase letters, numbers, and underscores
  return /^[a-z0-9_]+$/.test(name)
}

/**
 * Extract node ID from LangGraph node name (for debugging)
 *
 * @param nodeName - LangGraph node name
 * @returns First 8 characters of node ID, or null if extraction fails
 */
export function extractNodeIdFromName(nodeName: string): string | null {
  // Try to extract 8-character ID from the end
  const parts = nodeName.split('_')
  if (parts.length >= 2) {
    const lastPart = parts[parts.length - 1]
    if (lastPart.length === 8) {
      return lastPart
    }
  }
  return null
}

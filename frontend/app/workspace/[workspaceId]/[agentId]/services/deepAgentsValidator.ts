/**
 * DeepAgents Validator - Validates DeepAgents graph structure
 *
 * Validates DeepAgents-specific rules based on backend deep_agents_builder.py:
 * - Root node requirements
 * - DeepAgents structure constraints
 * - SubAgent requirements
 * - Edge direction rules
 */

import { Node, Edge } from 'reactflow'

import { ValidationError } from '../types/graph'

/**
 * Check if DeepAgents mode is enabled for a node
 * Matches backend logic: config.get("useDeepAgents", False) is True
 */
export function isDeepAgentsEnabled(node: Node): boolean {
  const data = node.data || {}
  const config = data.config || {}
  return config.useDeepAgents === true
}

/**
 * Get root nodes (nodes with no incoming edges)
 * Matches backend _find_root_nodes() logic
 */
export function getRootNodes(nodes: Node[], edges: Edge[]): Node[] {
  const targetIds = new Set(edges.map(edge => edge.target))
  return nodes.filter(node => !targetIds.has(node.id))
}

/**
 * Get direct children of a node
 * Matches backend _get_direct_children() logic
 */
export function getDirectChildren(nodeId: string, edges: Edge[]): string[] {
  return edges
    .filter(edge => edge.source === nodeId)
    .map(edge => edge.target)
}

/**
 * Get nodes by IDs
 */
function getNodesByIds(nodeIds: string[], nodes: Node[]): Node[] {
  return nodes.filter(node => nodeIds.includes(node.id))
}

/**
 * Validate DeepAgents graph structure
 *
 * Rules based on backend deep_agents_builder.py:
 * 1. Must have at least one root node
 * 2. Root node without children must have DeepAgents enabled
 * 3. SubAgents (children of Manager) must have description (≥10 chars)
 * 4. SubAgent count should be 3-8 (warning if outside range)
 * 5. No edges between SubAgents
 * 6. No edges pointing to Manager
 * 7. Only 2-level structure (Manager → SubAgent)
 */
export function validateDeepAgentsStructure(
  nodes: Node[],
  edges: Edge[]
): Array<ValidationError & { nodeId?: string; edgeId?: string }> {
  const errors: Array<ValidationError & { nodeId?: string; edgeId?: string }> = []

  // 1. Check root nodes
  const rootNodes = getRootNodes(nodes, edges)

  if (rootNodes.length === 0) {
    errors.push({
      field: 'deepAgents.rootNodes',
      message: 'Graph must have at least one root node (no incoming edges)',
      severity: 'error',
    })
    return errors // Early return if no root nodes
  }

  // 2. Check for multiple root nodes (orphan nodes / disconnected graph)
  // Multiple root nodes indicate disconnected graph structure, which is problematic
  if (rootNodes.length > 1) {
    // This is a graph structure issue - multiple disconnected components
    errors.push({
      field: 'deepAgents.multipleRoots',
      message: `Graph has ${rootNodes.length} root nodes (disconnected components). Graph should have only one entry point.`,
      severity: 'error',
    })

    // Also check if backend can select a root node
    const deepAgentsRoots = rootNodes.filter(node => isDeepAgentsEnabled(node))
    if (deepAgentsRoots.length === 0) {
      // Multiple roots without DeepAgents enabled - backend cannot select
      // Matches backend: "Cannot select root node - multiple roots without DeepAgents enabled"
      errors.push({
        field: 'deepAgents.multipleRoots.noSelection',
        message: 'Cannot select root node - multiple roots without DeepAgents enabled',
        severity: 'error',
      })
      // When backend cannot select root, it stops here
      // Still validate SubAgent rules for any root nodes that have children
    }
  }

  // 3. Select root node (exactly matches backend _select_root_node logic)
  // Backend logic: prefer DeepAgents-enabled, else single root
  const deepAgentsRoots = rootNodes.filter(node => isDeepAgentsEnabled(node))
  let selectedRootNode: Node | null = null

  if (deepAgentsRoots.length > 0) {
    // Backend will select the first DeepAgents-enabled root
    selectedRootNode = deepAgentsRoots[0]
  } else if (rootNodes.length === 1) {
    // Backend will select the single root (even if not DeepAgents-enabled)
    selectedRootNode = rootNodes[0]
  }
  // If multiple roots without DeepAgents, selectedRootNode remains null

  // 4. Validate selected root node (matches backend _build_graph logic)
  // This only runs if backend can select a root node
  if (selectedRootNode) {
    const children = getDirectChildren(selectedRootNode.id, edges)
    const hasChildren = children.length > 0
    const deepAgentsEnabled = isDeepAgentsEnabled(selectedRootNode)

    // Rule: Root node without children must have DeepAgents enabled
    // Matches backend: "Root node must have DeepAgents enabled" when no children
    // This check only applies to the root node that would be selected by backend
    if (!hasChildren && !deepAgentsEnabled) {
      errors.push({
        field: `deepAgents.rootNode.${selectedRootNode.id}`,
        message: 'Root node must have DeepAgents enabled',
        severity: 'error',
        nodeId: selectedRootNode.id,
      })
    }
  }

  // 5. Validate all root nodes for SubAgent rules (if they have children and DeepAgents enabled)
  for (const rootNode of rootNodes) {

    const children = getDirectChildren(rootNode.id, edges)
    const hasChildren = children.length > 0
    const deepAgentsEnabled = isDeepAgentsEnabled(rootNode)

    // Validate SubAgents (only if root has children and DeepAgents enabled)
    if (hasChildren && deepAgentsEnabled) {
      const childNodes = getNodesByIds(children, nodes)

      // 4.1 Check SubAgent count (3-8 recommended)
      if (childNodes.length < 3) {
        errors.push({
          field: `deepAgents.subAgentCount.${rootNode.id}`,
          message: `Manager has ${childNodes.length} subAgent(s). Recommended: 3-8 subAgents.`,
          severity: 'warning',
          nodeId: rootNode.id,
        })
      } else if (childNodes.length > 8) {
        errors.push({
          field: `deepAgents.subAgentCount.${rootNode.id}`,
          message: `Manager has ${childNodes.length} subAgents. Recommended: 3-8 subAgents. Consider merging similar subAgents.`,
          severity: 'warning',
          nodeId: rootNode.id,
        })
      }

      // 4.2 Check SubAgent descriptions
      for (const childNode of childNodes) {
        const childData = childNode.data || {}
        const childConfig = childData.config || {}
        const description = childConfig.description

        if (!description || typeof description !== 'string') {
          errors.push({
            field: `deepAgents.subAgent.description.${childNode.id}`,
            message: 'SubAgent must have a description field',
            severity: 'error',
            nodeId: childNode.id,
          })
        } else if (description.trim().length < 10) {
          errors.push({
            field: `deepAgents.subAgent.description.${childNode.id}`,
            message: 'SubAgent description must be at least 10 characters',
            severity: 'warning',
            nodeId: childNode.id,
          })
        }
      }

      // 4.3 Check for edges between SubAgents (forbidden)
      for (const edge of edges) {
        const sourceIsChild = children.includes(edge.source)
        const targetIsChild = children.includes(edge.target)

        if (sourceIsChild && targetIsChild) {
          errors.push({
            field: `deepAgents.edge.betweenSubAgents.${edge.id}`,
            message: 'Edges between SubAgents are not allowed. SubAgents communicate via shared backend.',
            severity: 'error',
            edgeId: edge.id,
            nodeId: edge.source, // Source SubAgent
          })
        }

        // 4.4 Check for edges pointing to Manager (forbidden)
        if (targetIsChild && edge.target === rootNode.id) {
          errors.push({
            field: `deepAgents.edge.toManager.${edge.id}`,
            message: 'Edges pointing to Manager are not allowed. Manager is the only entry point.',
            severity: 'error',
            edgeId: edge.id,
            nodeId: edge.source,
          })
        }
      }

      // 4.5 Check for nested SubAgents (only 2-level structure allowed)
      for (const childNode of childNodes) {
        const grandChildren = getDirectChildren(childNode.id, edges)
        if (grandChildren.length > 0) {
          errors.push({
            field: `deepAgents.hierarchy.${childNode.id}`,
            message: 'SubAgents cannot have their own SubAgents. Only 2-level structure (Manager → SubAgent) is supported.',
            severity: 'error',
            nodeId: childNode.id,
          })
        }
      }
    }
  }

  return errors
}

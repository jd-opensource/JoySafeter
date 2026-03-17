/**
 * Tree building utilities for execution stream.
 *
 * Converts flat ExecutionStep[] into a hierarchical ExecutionTreeNode tree.
 * Uses iterative algorithms (no recursion) to handle deep trees safely.
 *
 * Algorithm (N-level tree via parentObservationId):
 * 1. Each step has an observationId and optionally a parentObservationId
 * 2. If parentObservationId exists, find the parent tree node and nest under it
 * 3. If no parentObservationId, fall back to grouping by nodeId (2-level)
 * 4. Build flat list for virtualized rendering
 *
 * Main export: buildExecutionTree() — builds tree from flat steps array.
 */

import type {
  ExecutionStep,
  ExecutionTreeNode,
  ExecutionTreeNodeType,
  ExecutionTreeFlatItem,
} from '@/types'

/**
 * Maps step type to tree node type
 */
function getNodeType(step: ExecutionStep): ExecutionTreeNodeType {
  switch (step.stepType) {
    case 'node_lifecycle':
      return 'NODE'
    case 'tool_execution':
      return 'TOOL'
    case 'model_io':
      return 'MODEL'
    case 'agent_thought':
      return 'THOUGHT'
    case 'code_agent_thought':
    case 'code_agent_code':
    case 'code_agent_observation':
    case 'code_agent_final_answer':
    case 'code_agent_planning':
    case 'code_agent_error':
      return 'CODE_AGENT'
    default:
      return 'NODE'
  }
}

/**
 * Checks if steps contain observation-based hierarchy data.
 * Returns true if at least one step has parentObservationId set.
 */
function hasObservationHierarchy(steps: ExecutionStep[]): boolean {
  return steps.some(s => !!s.parentObservationId)
}

/**
 * Builds hierarchical tree from flat execution steps.
 *
 * Supports two strategies:
 *
 * Strategy A (parentObservationId present — N-level tree):
 *   Uses observationId/parentObservationId to build true N-level hierarchy.
 *   Each step maps to a tree node. Parent-child is determined by parentObservationId.
 *
 * Strategy B (legacy fallback — 2-level tree):
 *   Groups steps by nodeId. node_lifecycle steps become parent nodes,
 *   all other steps nest under the matching nodeId parent.
 *
 * Returns roots, nodeMap.
 */
export function buildExecutionTree(steps: ExecutionStep[]): {
  roots: ExecutionTreeNode[]
  nodeMap: Map<string, ExecutionTreeNode>
} {
  if (steps.length === 0) {
    return { roots: [], nodeMap: new Map() }
  }

  // Decide strategy
  if (hasObservationHierarchy(steps)) {
    return buildTreeByObservation(steps)
  }
  return buildTreeByNodeId(steps)
}

/**
 * Strategy A: Build N-level tree using parentObservationId.
 */
function buildTreeByObservation(steps: ExecutionStep[]): {
  roots: ExecutionTreeNode[]
  nodeMap: Map<string, ExecutionTreeNode>
} {
  const nodeMap = new Map<string, ExecutionTreeNode>()
  // Map observationId -> tree node (for parent lookups)
  const obsMap = new Map<string, ExecutionTreeNode>()
  const roots: ExecutionTreeNode[] = []
  const traceStartTime = steps[0].startTime

  // Pass 1: Create all tree nodes
  for (const step of steps) {
    const treeNode: ExecutionTreeNode = {
      id: step.id,
      type: getNodeType(step),
      name: step.nodeLabel || step.title,
      startTime: step.startTime,
      endTime: step.endTime,
      duration: step.duration,
      status: step.status,
      children: [],
      depth: 0, // will be computed in pass 2
      childrenDepth: 0,
      startTimeSinceTrace: step.startTime - traceStartTime,
      step,
      parentId: undefined,
    }
    nodeMap.set(step.id, treeNode)
    if (step.observationId) {
      obsMap.set(step.observationId, treeNode)
    }
  }

  // Pass 2: Build parent-child relationships
  for (const step of steps) {
    const treeNode = nodeMap.get(step.id)!
    if (step.parentObservationId) {
      const parent = obsMap.get(step.parentObservationId)
      if (parent) {
        treeNode.parentId = parent.id
        parent.children.push(treeNode)
        continue
      }
    }
    // No parent found — this is a root
    roots.push(treeNode)
  }

  // Pass 3: Compute depth and childrenDepth bottom-up (iterative BFS)
  // First, set depth using BFS from roots
  const queue: ExecutionTreeNode[] = [...roots]
  for (const r of queue) { r.depth = 0 }
  while (queue.length > 0) {
    const node = queue.shift()!
    for (const child of node.children) {
      child.depth = node.depth + 1
      queue.push(child)
    }
  }

  // Compute childrenDepth bottom-up: post-order traversal
  // Use iterative approach with a stack
  const postOrderStack: ExecutionTreeNode[] = []
  const dfsStack = [...roots]
  while (dfsStack.length > 0) {
    const node = dfsStack.pop()!
    postOrderStack.push(node)
    for (const child of node.children) {
      dfsStack.push(child)
    }
  }
  // Process in reverse order (leaves first)
  for (let i = postOrderStack.length - 1; i >= 0; i--) {
    const node = postOrderStack[i]
    if (node.children.length === 0) {
      node.childrenDepth = 0
    } else {
      node.childrenDepth = 1 + Math.max(...node.children.map(c => c.childrenDepth))
    }
  }

  // Pass 4: Update durations for nodes with children but no explicit duration
  for (const [, node] of nodeMap) {
    if (!node.duration && node.children.length > 0) {
      const lastChild = node.children[node.children.length - 1]
      if (lastChild.endTime && node.startTime) {
        node.duration = lastChild.endTime - node.startTime
      }
    }
  }

  return { roots, nodeMap }
}

/**
 * Strategy B: Legacy 2-level tree (group by nodeId).
 * Used when SSE events don't have parentObservationId.
 */
function buildTreeByNodeId(steps: ExecutionStep[]): {
  roots: ExecutionTreeNode[]
  nodeMap: Map<string, ExecutionTreeNode>
} {
  const nodeMap = new Map<string, ExecutionTreeNode>()
  const nodeParentMap = new Map<string, ExecutionTreeNode>()
  const roots: ExecutionTreeNode[] = []
  const traceStartTime = steps[0].startTime

  for (const step of steps) {
    if (step.stepType === 'node_lifecycle') {
      const treeNode: ExecutionTreeNode = {
        id: step.id,
        type: 'NODE',
        name: step.nodeLabel || step.title,
        startTime: step.startTime,
        endTime: step.endTime,
        duration: step.duration,
        status: step.status,
        children: [],
        depth: 0,
        childrenDepth: 0,
        startTimeSinceTrace: step.startTime - traceStartTime,
        step,
        parentId: undefined,
      }
      nodeMap.set(step.id, treeNode)
      nodeParentMap.set(step.nodeId, treeNode)
      roots.push(treeNode)
    } else {
      const parent = nodeParentMap.get(step.nodeId)
      const treeNode: ExecutionTreeNode = {
        id: step.id,
        type: getNodeType(step),
        name: step.title,
        startTime: step.startTime,
        endTime: step.endTime,
        duration: step.duration,
        status: step.status,
        children: [],
        depth: parent ? 1 : 0,
        childrenDepth: 0,
        startTimeSinceTrace: step.startTime - traceStartTime,
        step,
        parentId: parent?.id,
      }
      nodeMap.set(step.id, treeNode)
      if (parent) {
        parent.children.push(treeNode)
        parent.childrenDepth = Math.max(parent.childrenDepth, 1)
      } else {
        roots.push(treeNode)
      }
    }
  }

  // Update durations for parent nodes
  for (const root of roots) {
    if (!root.duration && root.children.length > 0) {
      const lastChild = root.children[root.children.length - 1]
      if (lastChild.endTime && root.startTime) {
        root.duration = lastChild.endTime - root.startTime
      }
    }
  }

  return { roots, nodeMap }
}

/**
 * Flattens tree into a list for virtualized rendering.
 * Respects collapsed/expanded state.
 * Uses iterative DFS to avoid stack overflow on deep trees.
 */
export function flattenTree(
  roots: ExecutionTreeNode[],
  collapsedIds: Set<string>
): ExecutionTreeFlatItem[] {
  const items: ExecutionTreeFlatItem[] = []

  // Iterative pre-order DFS using explicit stack
  // Push roots in reverse order for correct left-to-right traversal
  const stack: ExecutionTreeNode[] = []
  for (let i = roots.length - 1; i >= 0; i--) {
    stack.push(roots[i])
  }

  while (stack.length > 0) {
    const node = stack.pop()!
    const hasChildren = node.children.length > 0
    const isExpanded = hasChildren && !collapsedIds.has(node.id)

    items.push({
      node,
      isExpanded,
      hasChildren,
    })

    // If expanded, push children in reverse order
    if (isExpanded) {
      for (let i = node.children.length - 1; i >= 0; i--) {
        stack.push(node.children[i])
      }
    }
  }

  return items
}

/**
 * Computes total duration of the trace from roots.
 * Iteratively traverses the entire tree to find the latest endTime.
 */
export function getTraceDuration(roots: ExecutionTreeNode[]): number {
  if (roots.length === 0) return 0

  const traceStart = roots[0].startTime
  let traceEnd = traceStart

  // Iterative DFS to find max endTime across all tree levels
  const stack: ExecutionTreeNode[] = [...roots]
  while (stack.length > 0) {
    const node = stack.pop()!
    const nodeEnd = node.endTime || node.startTime
    if (nodeEnd > traceEnd) traceEnd = nodeEnd
    for (const child of node.children) {
      stack.push(child)
    }
  }

  return traceEnd - traceStart
}

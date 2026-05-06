import type {
  RawObservation,
  ObservationNode,
  ProcessingNode,
  TraceTreeResult,
  SearchItem,
} from './types'

function prepareObservations(observations: RawObservation[]): {
  sorted: RawObservation[]
  orphanedCount: number
} {
  const idSet = new Set(observations.map((o) => o.id))
  let orphanedCount = 0

  const normalized = observations.map((o) => {
    if (o.parentObservationId !== null && !idSet.has(o.parentObservationId)) {
      orphanedCount++
      return { ...o, parentObservationId: null }
    }
    return o
  })

  const sorted = normalized
    .slice()
    .sort((a, b) => new Date(a.startTime).getTime() - new Date(b.startTime).getTime())

  return { sorted, orphanedCount }
}

function buildDependencyGraph(observations: RawObservation[]): {
  processingMap: Map<string, ProcessingNode>
  leaves: string[]
} {
  const processingMap = new Map<string, ProcessingNode>()

  for (const obs of observations) {
    processingMap.set(obs.id, {
      observation: obs,
      childrenIds: [],
      inDegree: 0,
      depth: 0,
    })
  }

  for (const obs of observations) {
    if (obs.parentObservationId !== null) {
      const parent = processingMap.get(obs.parentObservationId)
      if (parent) {
        parent.childrenIds.push(obs.id)
      }
    }
  }

  // BFS from roots to compute depth
  const roots = observations.filter((o) => o.parentObservationId === null).map((o) => o.id)

  const queue = [...roots]
  let qi = 0
  while (qi < queue.length) {
    const id = queue[qi++]
    const node = processingMap.get(id)!
    for (const childId of node.childrenIds) {
      const child = processingMap.get(childId)!
      child.depth = node.depth + 1
      queue.push(childId)
    }
  }

  // inDegree = number of children (used for bottom-up topo sort)
  for (const node of processingMap.values()) {
    node.inDegree = node.childrenIds.length
  }

  const leaves = Array.from(processingMap.values())
    .filter((n) => n.inDegree === 0)
    .map((n) => n.observation.id)

  return { processingMap, leaves }
}

function buildTreeNodesBottomUp(
  processingMap: Map<string, ProcessingNode>,
  leaves: string[],
  traceStartTime: Date,
): Map<string, ObservationNode> {
  const treeNodeMap = new Map<string, ObservationNode>()
  const queue = [...leaves]
  let qi = 0

  while (qi < queue.length) {
    const id = queue[qi++]
    const pNode = processingMap.get(id)!
    const obs = pNode.observation

    const childTreeNodes = pNode.childrenIds
      .map((cid) => processingMap.get(cid)?.treeNode)
      .filter((n): n is ObservationNode => n !== undefined)
      .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())

    const nodeCost =
      obs.calculatedTotalCost ?? (obs.calculatedInputCost ?? 0) + (obs.calculatedOutputCost ?? 0)
    const totalCost = nodeCost + childTreeNodes.reduce((sum, c) => sum + c.totalCost, 0)

    const startTime = new Date(obs.startTime)
    const endTime = obs.endTime ? new Date(obs.endTime) : null
    const completionStartTime = obs.completionStartTime ? new Date(obs.completionStartTime) : null

    const latency = endTime !== null ? (endTime.getTime() - startTime.getTime()) / 1000 : null

    const startTimeSinceTrace = startTime.getTime() - traceStartTime.getTime()

    let startTimeSinceParentStart: number | null = null
    if (obs.parentObservationId !== null) {
      const parentPNode = processingMap.get(obs.parentObservationId)
      if (parentPNode) {
        const parentStart = new Date(parentPNode.observation.startTime)
        startTimeSinceParentStart = startTime.getTime() - parentStart.getTime()
      }
    }

    const childrenDepth =
      childTreeNodes.length > 0 ? Math.max(...childTreeNodes.map((c) => c.childrenDepth)) + 1 : 0

    const inputUsage = obs.usageDetails?.input ?? null
    const outputUsage = obs.usageDetails?.output ?? null
    const totalUsage =
      obs.usageDetails?.total ??
      (inputUsage !== null || outputUsage !== null ? (inputUsage ?? 0) + (outputUsage ?? 0) : null)

    const treeNode: ObservationNode = {
      id: obs.id,
      parentObservationId: obs.parentObservationId,
      traceId: obs.traceId,
      type: obs.type,
      name: obs.name,
      level: obs.level,
      statusMessage: obs.statusMessage,
      startTime,
      endTime,
      completionStartTime,
      input: obs.input,
      output: obs.output,
      metadata: obs.metadata,
      model: obs.model,
      modelParameters: obs.modelParameters,
      usageDetails: obs.usageDetails,
      calculatedInputCost: obs.calculatedInputCost,
      calculatedOutputCost: obs.calculatedOutputCost,
      calculatedTotalCost: obs.calculatedTotalCost,
      environment: obs.environment,
      promptName: obs.promptName,
      promptVersion: obs.promptVersion,
      children: childTreeNodes,
      depth: pNode.depth,
      childrenDepth,
      totalCost,
      inputUsage,
      outputUsage,
      totalUsage,
      latency,
      startTimeSinceTrace,
      startTimeSinceParentStart,
    }

    pNode.treeNode = treeNode
    treeNodeMap.set(id, treeNode)

    if (obs.parentObservationId !== null) {
      const parentPNode = processingMap.get(obs.parentObservationId)
      if (parentPNode) {
        parentPNode.inDegree--
        if (parentPNode.inDegree === 0) {
          queue.push(obs.parentObservationId)
        }
      }
    }
  }

  return treeNodeMap
}

export function buildTraceTree(
  observations: RawObservation[],
  traceStartTime: Date,
): TraceTreeResult {
  if (observations.length === 0) {
    return { roots: [], nodeMap: new Map(), searchItems: [] }
  }

  const { sorted } = prepareObservations(observations)
  const { processingMap, leaves } = buildDependencyGraph(sorted)
  const nodeMap = buildTreeNodesBottomUp(processingMap, leaves, traceStartTime)

  const roots = sorted
    .filter((o) => o.parentObservationId === null)
    .map((o) => nodeMap.get(o.id)!)
    .filter(Boolean)
    .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())

  // Pre-order traversal for searchItems
  const searchItems: SearchItem[] = []
  const stack = [...roots].reverse()
  while (stack.length > 0) {
    const node = stack.pop()!
    searchItems.push({ node, observationId: node.id })
    for (let i = node.children.length - 1; i >= 0; i--) {
      stack.push(node.children[i])
    }
  }

  return { roots, nodeMap, searchItems }
}

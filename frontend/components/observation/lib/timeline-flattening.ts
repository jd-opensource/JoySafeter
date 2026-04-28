import type { ObservationNode, TimelineFlatItem, TimelineMetrics } from './types'
import {
  calculateTimelineOffset,
  calculateTimelineWidth,
  SCALE_WIDTH,
} from './timeline-calculations'

export function flattenTreeWithTimelineMetrics(
  roots: ObservationNode[],
  collapsedNodes: Set<string>,
  traceStartTime: Date,
  totalScaleSpan: number,
  scaleWidth: number = SCALE_WIDTH,
): TimelineFlatItem[] {
  const flatList: TimelineFlatItem[] = []

  const sortedRoots = roots
    .slice()
    .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())

  type StackItem = {
    node: ObservationNode
    depth: number
    treeLines: boolean[]
    isLastSibling: boolean
  }

  const stack: StackItem[] = []

  for (let i = sortedRoots.length - 1; i >= 0; i--) {
    stack.push({
      node: sortedRoots[i],
      depth: 0,
      treeLines: [],
      isLastSibling: i === sortedRoots.length - 1,
    })
  }

  while (stack.length > 0) {
    const current = stack.pop()!
    const { node } = current

    const latency =
      node.endTime !== null
        ? (node.endTime.getTime() - node.startTime.getTime()) / 1000
        : undefined

    const startOffset = calculateTimelineOffset(
      node.startTime,
      traceStartTime,
      totalScaleSpan,
      scaleWidth,
    )

    const itemWidth = calculateTimelineWidth(
      latency ?? 0,
      totalScaleSpan,
      scaleWidth,
    )

    const firstTokenTimeOffset = node.completionStartTime
      ? calculateTimelineOffset(
          node.completionStartTime,
          traceStartTime,
          totalScaleSpan,
          scaleWidth,
        )
      : undefined

    const metrics: TimelineMetrics = {
      startOffset,
      itemWidth,
      firstTokenTimeOffset,
      latency,
    }

    flatList.push({
      node,
      depth: current.depth,
      treeLines: current.treeLines,
      isLastSibling: current.isLastSibling,
      metrics,
    })

    if (node.children.length > 0 && !collapsedNodes.has(node.id)) {
      const sortedChildren = node.children
        .slice()
        .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())

      for (let i = sortedChildren.length - 1; i >= 0; i--) {
        const isChildLast = i === sortedChildren.length - 1
        stack.push({
          node: sortedChildren[i],
          depth: current.depth + 1,
          treeLines: [...current.treeLines, !isChildLast],
          isLastSibling: isChildLast,
        })
      }
    }
  }

  return flatList
}

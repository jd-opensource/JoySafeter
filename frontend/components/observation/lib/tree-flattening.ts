import type { ObservationNode, ObservationFlatItem } from './types'

export function flattenTree(
  roots: ObservationNode[],
  collapsedNodes: Set<string>,
): ObservationFlatItem[] {
  const flatList: ObservationFlatItem[] = []

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
    flatList.push({
      node: current.node,
      depth: current.depth,
      isLastSibling: current.isLastSibling,
      treeLines: current.treeLines,
    })

    if (
      current.node.children.length > 0 &&
      !collapsedNodes.has(current.node.id)
    ) {
      const sortedChildren = current.node.children
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

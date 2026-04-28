import { describe, it, expect } from 'vitest'
import { flattenTree } from '../lib/tree-flattening'
import type { ObservationNode } from '../lib/types'

function makeNode(
  id: string,
  children: ObservationNode[] = [],
  startMs = 0,
): ObservationNode {
  return {
    id,
    parentObservationId: null,
    traceId: 'trace-1',
    type: 'SPAN',
    name: id,
    level: 'DEFAULT',
    statusMessage: null,
    startTime: new Date(startMs),
    endTime: new Date(startMs + 1000),
    completionStartTime: null,
    input: null,
    output: null,
    metadata: null,
    children,
    depth: 0,
    childrenDepth: 0,
    totalCost: 0,
    inputUsage: null,
    outputUsage: null,
    totalUsage: null,
    latency: 1,
    startTimeSinceTrace: startMs,
    startTimeSinceParentStart: null,
  }
}

describe('flattenTree', () => {
  it('empty roots → empty list', () => {
    expect(flattenTree([], new Set())).toHaveLength(0)
  })

  it('single root no children → single item, treeLines=[]', () => {
    const root = makeNode('a')
    const result = flattenTree([root], new Set())
    expect(result).toHaveLength(1)
    expect(result[0].treeLines).toEqual([])
    expect(result[0].depth).toBe(0)
  })

  it('collapsed node → children not in flatList', () => {
    const child = makeNode('c')
    const root = makeNode('p', [child])
    const result = flattenTree([root], new Set(['p']))
    expect(result).toHaveLength(1)
    expect(result[0].node.id).toBe('p')
  })

  it('treeLines: non-last sibling ancestor → true', () => {
    const c1 = makeNode('c1', [], 0)
    const c2 = makeNode('c2', [], 10)
    const root = makeNode('p', [c1, c2])
    const result = flattenTree([root], new Set())
    // c1 is not last sibling → treeLines[0] should be true (parent has more siblings below)
    const c1Item = result.find((i) => i.node.id === 'c1')!
    const c2Item = result.find((i) => i.node.id === 'c2')!
    expect(c1Item.isLastSibling).toBe(false)
    expect(c2Item.isLastSibling).toBe(true)
  })

  it('isLastSibling correctly marked', () => {
    const c1 = makeNode('c1', [], 0)
    const c2 = makeNode('c2', [], 10)
    const c3 = makeNode('c3', [], 20)
    const root = makeNode('p', [c1, c2, c3])
    const result = flattenTree([root], new Set())
    const ids = result.map((i) => i.node.id)
    expect(ids).toEqual(['p', 'c1', 'c2', 'c3'])
    expect(result[3].isLastSibling).toBe(true)
    expect(result[2].isLastSibling).toBe(false)
  })

  it('multiple roots sorted by startTime', () => {
    const r1 = makeNode('r1', [], 200)
    const r2 = makeNode('r2', [], 100)
    const r3 = makeNode('r3', [], 300)
    const result = flattenTree([r1, r2, r3], new Set())
    expect(result.map((i) => i.node.id)).toEqual(['r2', 'r1', 'r3'])
  })

  it('deep nesting (100 levels) does not stack overflow', () => {
    let node = makeNode('leaf')
    for (let i = 99; i >= 0; i--) {
      node = makeNode(`n${i}`, [node], i)
    }
    expect(() => flattenTree([node], new Set())).not.toThrow()
  })
})

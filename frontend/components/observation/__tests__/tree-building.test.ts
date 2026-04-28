import { describe, it, expect } from 'vitest'
import { buildTraceTree } from '../lib/tree-building'
import type { RawObservation } from '../lib/types'

function makeObs(
  overrides: Partial<RawObservation> & { id: string },
): RawObservation {
  return {
    traceId: 'trace-1',
    parentObservationId: null,
    type: 'SPAN',
    name: overrides.id,
    level: 'DEFAULT',
    statusMessage: null,
    startTime: new Date(0).toISOString(),
    endTime: new Date(1000).toISOString(),
    completionStartTime: null,
    input: null,
    output: null,
    metadata: null,
    ...overrides,
  }
}

const T0 = new Date(0)

describe('buildTraceTree', () => {
  it('returns empty result for empty input', () => {
    const result = buildTraceTree([], T0)
    expect(result.roots).toHaveLength(0)
    expect(result.nodeMap.size).toBe(0)
    expect(result.searchItems).toHaveLength(0)
  })

  it('single node → single root, depth=0, childrenDepth=0', () => {
    const obs = makeObs({ id: 'a', startTime: new Date(0).toISOString() })
    const result = buildTraceTree([obs], T0)
    expect(result.roots).toHaveLength(1)
    expect(result.roots[0].depth).toBe(0)
    expect(result.roots[0].childrenDepth).toBe(0)
    expect(result.roots[0].children).toHaveLength(0)
  })

  it('parent→child: correct depth and children', () => {
    const parent = makeObs({ id: 'p', startTime: new Date(0).toISOString() })
    const child = makeObs({
      id: 'c',
      parentObservationId: 'p',
      startTime: new Date(100).toISOString(),
    })
    const result = buildTraceTree([parent, child], T0)
    expect(result.roots).toHaveLength(1)
    const root = result.roots[0]
    expect(root.id).toBe('p')
    expect(root.depth).toBe(0)
    expect(root.childrenDepth).toBe(1)
    expect(root.children).toHaveLength(1)
    expect(root.children[0].id).toBe('c')
    expect(root.children[0].depth).toBe(1)
  })

  it('3-level nesting: depth increments correctly', () => {
    const a = makeObs({ id: 'a', startTime: new Date(0).toISOString() })
    const b = makeObs({ id: 'b', parentObservationId: 'a', startTime: new Date(10).toISOString() })
    const c = makeObs({ id: 'c', parentObservationId: 'b', startTime: new Date(20).toISOString() })
    const result = buildTraceTree([a, b, c], T0)
    const root = result.roots[0]
    expect(root.depth).toBe(0)
    expect(root.children[0].depth).toBe(1)
    expect(root.children[0].children[0].depth).toBe(2)
    expect(root.childrenDepth).toBe(2)
  })

  it('orphaned parentObservationId → promoted to root', () => {
    const obs = makeObs({ id: 'x', parentObservationId: 'nonexistent' })
    const result = buildTraceTree([obs], T0)
    expect(result.roots).toHaveLength(1)
    expect(result.roots[0].parentObservationId).toBeNull()
    expect(result.roots[0].depth).toBe(0)
  })

  it('bottom-up cost aggregation', () => {
    const parent = makeObs({ id: 'p', calculatedTotalCost: 0.01 })
    const child1 = makeObs({ id: 'c1', parentObservationId: 'p', calculatedTotalCost: 0.02 })
    const child2 = makeObs({ id: 'c2', parentObservationId: 'p', calculatedTotalCost: 0.03 })
    const result = buildTraceTree([parent, child1, child2], T0)
    const root = result.roots[0]
    expect(root.totalCost).toBeCloseTo(0.06)
  })

  it('startTimeSinceTrace is correct', () => {
    const traceStart = new Date(1000)
    const obs = makeObs({ id: 'a', startTime: new Date(1500).toISOString() })
    const result = buildTraceTree([obs], traceStart)
    expect(result.roots[0].startTimeSinceTrace).toBe(500)
  })

  it('startTimeSinceParentStart is correct', () => {
    const parent = makeObs({ id: 'p', startTime: new Date(1000).toISOString() })
    const child = makeObs({
      id: 'c',
      parentObservationId: 'p',
      startTime: new Date(1200).toISOString(),
    })
    const result = buildTraceTree([parent, child], T0)
    expect(result.roots[0].children[0].startTimeSinceParentStart).toBe(200)
  })

  it('children sorted by startTime', () => {
    const parent = makeObs({ id: 'p', startTime: new Date(0).toISOString() })
    const c1 = makeObs({ id: 'c1', parentObservationId: 'p', startTime: new Date(300).toISOString() })
    const c2 = makeObs({ id: 'c2', parentObservationId: 'p', startTime: new Date(100).toISOString() })
    const c3 = makeObs({ id: 'c3', parentObservationId: 'p', startTime: new Date(200).toISOString() })
    const result = buildTraceTree([parent, c1, c2, c3], T0)
    const ids = result.roots[0].children.map((c) => c.id)
    expect(ids).toEqual(['c2', 'c3', 'c1'])
  })

  it('10,000 nodes completes in < 500ms', () => {
    const obs: RawObservation[] = []
    obs.push(makeObs({ id: 'root', startTime: new Date(0).toISOString() }))
    for (let i = 1; i < 10000; i++) {
      obs.push(
        makeObs({
          id: `n${i}`,
          parentObservationId: `n${i - 1}` === 'n0' ? 'root' : `n${i - 1}`,
          startTime: new Date(i).toISOString(),
        }),
      )
    }
    const start = Date.now()
    buildTraceTree(obs, T0)
    expect(Date.now() - start).toBeLessThan(500)
  })
})

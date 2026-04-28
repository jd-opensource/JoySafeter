import { describe, it, expect } from 'vitest'
import {
  calculateTimelineOffset,
  calculateTimelineWidth,
  calculateStepSize,
  SCALE_WIDTH,
  STEP_SIZE,
} from '../lib/timeline-calculations'

describe('calculateTimelineOffset', () => {
  const traceStart = new Date('2024-01-01T00:00:00Z')

  it('returns 0 for node at trace start', () => {
    expect(calculateTimelineOffset(traceStart, traceStart, 10)).toBe(0)
  })

  it('returns SCALE_WIDTH for node at trace end', () => {
    const nodeStart = new Date('2024-01-01T00:00:10Z')
    expect(calculateTimelineOffset(nodeStart, traceStart, 10)).toBe(SCALE_WIDTH)
  })

  it('returns midpoint for node at half duration', () => {
    const nodeStart = new Date('2024-01-01T00:00:05Z')
    expect(calculateTimelineOffset(nodeStart, traceStart, 10)).toBe(SCALE_WIDTH / 2)
  })

  it('returns negative for node before trace start', () => {
    const nodeStart = new Date('2023-12-31T23:59:59Z')
    expect(calculateTimelineOffset(nodeStart, traceStart, 10)).toBeLessThan(0)
  })
})

describe('calculateTimelineWidth', () => {
  it('returns 0 for zero duration', () => {
    expect(calculateTimelineWidth(0, 10)).toBe(0)
  })

  it('returns SCALE_WIDTH for full duration', () => {
    expect(calculateTimelineWidth(10, 10)).toBe(SCALE_WIDTH)
  })

  it('returns proportional width', () => {
    expect(calculateTimelineWidth(5, 10)).toBe(SCALE_WIDTH / 2)
  })
})

describe('calculateStepSize', () => {
  it('returns 0.25 for very short trace', () => {
    expect(calculateStepSize(0.5)).toBe(0.25)
  })

  it('returns 500 for very long trace', () => {
    expect(calculateStepSize(10000)).toBe(500)
  })

  it('selects nearest predefined step size', () => {
    const step = calculateStepSize(50)
    expect(step).toBeGreaterThanOrEqual(50 / (SCALE_WIDTH / STEP_SIZE))
  })
})

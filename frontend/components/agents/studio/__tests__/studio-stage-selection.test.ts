import { describe, expect, it } from 'vitest'

import {
  AGENT_STUDIO_STAGES,
  getDefaultStudioStage,
  isStudioStage,
  normalizeStudioStage,
} from '../studio-types'

describe('Agent Studio stage helpers', () => {
  it('defines the Visual Agent stage order', () => {
    expect(AGENT_STUDIO_STAGES.map((stage) => stage.id)).toEqual([
      'brief',
      'canvas',
      'test-lab',
      'release',
      'usage',
    ])
  })

  it('uses brief as the default for an empty graph', () => {
    expect(getDefaultStudioStage({ nodesCount: 0, hasActiveRelease: false })).toBe('brief')
  })

  it('uses canvas as the default when graph nodes already exist', () => {
    expect(getDefaultStudioStage({ nodesCount: 2, hasActiveRelease: false })).toBe('canvas')
  })

  it('normalizes unknown stage values to the computed default', () => {
    expect(normalizeStudioStage('unknown', { nodesCount: 1, hasActiveRelease: true })).toBe('canvas')
  })

  it('recognizes only known stage ids', () => {
    expect(isStudioStage('release')).toBe(true)
    expect(isStudioStage('versions')).toBe(false)
  })
})

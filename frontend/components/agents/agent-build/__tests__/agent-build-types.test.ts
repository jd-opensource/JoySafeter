import { describe, it, expect } from 'vitest'
import { BUILD_STAGES, resolveDefaultStage, isBuildStageId } from '../agent-build-types'

describe('BUILD_STAGES', () => {
  it('defines exactly 5 stages in order', () => {
    expect(BUILD_STAGES.map((s) => s.id)).toEqual(['brief', 'build', 'test-lab', 'release', 'usage'])
  })
  it('each stage has icon, labelKey, descriptionKey', () => {
    for (const stage of BUILD_STAGES) {
      expect(stage.icon).toBeDefined()
      expect(stage.labelKey).toMatch(/^agents\.build\.stages\./)
      expect(stage.descriptionKey).toMatch(/^agents\.build\.stageDescriptions\./)
    }
  })
})

describe('isBuildStageId', () => {
  it('returns true for valid stage ids', () => {
    expect(isBuildStageId('brief')).toBe(true)
    expect(isBuildStageId('build')).toBe(true)
    expect(isBuildStageId('test-lab')).toBe(true)
    expect(isBuildStageId('release')).toBe(true)
    expect(isBuildStageId('usage')).toBe(true)
  })
  it('returns false for invalid values', () => {
    expect(isBuildStageId('canvas')).toBe(false)
    expect(isBuildStageId(null)).toBe(false)
    expect(isBuildStageId(undefined)).toBe(false)
  })
})

describe('resolveDefaultStage', () => {
  const baseAgent = { active_release_id: null } as any
  it('returns brief when no version', () => {
    expect(resolveDefaultStage(baseAgent, null)).toBe('brief')
  })
  it('returns brief when version has empty payload', () => {
    const version = { definition_payload: { nodes: [] } } as any
    expect(resolveDefaultStage(baseAgent, version)).toBe('brief')
  })
  it('returns build when version has nodes', () => {
    const version = { definition_payload: { nodes: [{}] } } as any
    expect(resolveDefaultStage(baseAgent, version)).toBe('build')
  })
  it('returns usage when agent has active release', () => {
    const agent = { active_release_id: 'rel-1' } as any
    const version = { definition_payload: { nodes: [{}] } } as any
    expect(resolveDefaultStage(agent, version)).toBe('usage')
  })
})

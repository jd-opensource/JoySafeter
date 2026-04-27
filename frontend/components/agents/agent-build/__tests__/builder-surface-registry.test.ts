import { describe, it, expect } from 'vitest'

import { resolveBuilderSurface } from '../builder-surface-registry'

describe('resolveBuilderSurface', () => {
  it('returns visual surface for graph', () => {
    const surface = resolveBuilderSurface('graph')
    expect(surface.BriefStage).toBeDefined()
    expect(surface.BuildStage).toBeDefined()
    expect(surface.TestLabStage).toBeDefined()
  })

  it('returns placeholder surface for code', () => {
    const surface = resolveBuilderSurface('code')
    expect(surface.BriefStage).toBeDefined()
  })

  it('returns the shared sandbox builder surface for CLI-backed definition kinds', () => {
    const claudeCode = resolveBuilderSurface('claude_code')
    expect(resolveBuilderSurface('codex')).toBe(claudeCode)
    expect(resolveBuilderSurface('openclaw')).toBe(claudeCode)
  })

  it('defaults to visual for null/undefined', () => {
    expect(resolveBuilderSurface(null)).toBe(resolveBuilderSurface('graph'))
    expect(resolveBuilderSurface(undefined)).toBe(resolveBuilderSurface('graph'))
  })
})

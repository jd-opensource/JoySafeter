import { describe, it, expect } from 'vitest'

import { ENGINE_KINDS } from '@/types/agent'

import { resolveBuilderSurface } from '../builder-surface-registry'

describe('resolveBuilderSurface', () => {
  it('resolves every supported engine kind to a complete builder surface', () => {
    for (const engineKind of ENGINE_KINDS) {
      const surface = resolveBuilderSurface(engineKind)
      expect(surface.BriefStage).toBeDefined()
      expect(surface.BuildStage).toBeDefined()
      expect(surface.TestLabStage).toBeDefined()
    }
  })

  it('returns visual surface for langgraph_visual', () => {
    const surface = resolveBuilderSurface('langgraph_visual')
    expect(surface.BriefStage).toBeDefined()
    expect(surface.BuildStage).toBeDefined()
    expect(surface.TestLabStage).toBeDefined()
  })

  it('returns placeholder surface for langgraph_code', () => {
    const surface = resolveBuilderSurface('langgraph_code')
    expect(surface.BriefStage).toBeDefined()
    expect(surface.BuildStage).toBeDefined()
    expect(surface.TestLabStage).toBeDefined()
  })

  it('returns the shared sandbox builder surface for CLI-backed definition kinds', () => {
    const claudeCode = resolveBuilderSurface('claude_code')
    expect(resolveBuilderSurface('codex')).toBe(claudeCode)
    expect(resolveBuilderSurface('openclaw')).toBe(claudeCode)
  })

  it('defaults to visual for null/undefined', () => {
    expect(resolveBuilderSurface(null)).toBe(resolveBuilderSurface('langgraph_visual'))
    expect(resolveBuilderSurface(undefined)).toBe(resolveBuilderSurface('langgraph_visual'))
  })
})

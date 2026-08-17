import { describe, expect, it } from 'vitest'
import { inferSchemeFromValues, resolveAnthropicScheme } from './anthropic-auth'

describe('resolveAnthropicScheme', () => {
  it('auto: official host -> xapikey', () => {
    expect(resolveAnthropicScheme('https://api.anthropic.com', 'auto')).toBe('xapikey')
    expect(resolveAnthropicScheme('', 'auto')).toBe('xapikey')
  })
  it('auto: gateway host -> bearer', () => {
    expect(resolveAnthropicScheme('http://ai-api.jdcloud.com/anthropic', 'auto')).toBe('bearer')
  })
  it('manual overrides host', () => {
    expect(resolveAnthropicScheme('https://api.anthropic.com', 'bearer')).toBe('bearer')
    expect(resolveAnthropicScheme('http://gw.example.com', 'xapikey')).toBe('xapikey')
  })
})

describe('inferSchemeFromValues', () => {
  it('reads back stored field', () => {
    expect(inferSchemeFromValues({ ANTHROPIC_AUTH_TOKEN: 'tok' })).toBe('bearer')
    expect(inferSchemeFromValues({ ANTHROPIC_API_KEY: 'k' })).toBe('xapikey')
    expect(inferSchemeFromValues({})).toBe('auto')
  })
})

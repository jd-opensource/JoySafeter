import { describe, expect, it } from 'vitest'

import type { Secret } from '@/types/managed'

import { selectInitialSecret } from '@/lib/managed/llm-selection'

function secret(name: string, isDefault = false): Secret {
  return {
    id: `secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f02${name.length}` as Secret['id'],
    name,
    kind: 'llm',
    provider: 'openai',
    protocol: 'openai_responses',
    model: 'gpt-5',
    compatible_engine_ids: ['codex'],
    is_default: isDefault,
    keys: ['OPENAI_API_KEY'],
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  }
}

describe('selectInitialSecret', () => {
  it('selects a single option or a unique default only', () => {
    expect(selectInitialSecret([secret('only')])).toBe('only')
    expect(selectInitialSecret([secret('a'), secret('default', true), secret('b')])).toBe(
      'default',
    )
    expect(selectInitialSecret([secret('a'), secret('b')])).toBe('')
    expect(selectInitialSecret([secret('a', true), secret('b', true)])).toBe('')
  })
})

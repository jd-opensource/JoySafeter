import { describe, expect, it } from 'vitest'

import type { Credential } from '@/types/managed'

import { selectInitialModelConnection } from '@/lib/managed/model-connection-selection'

function credential(name: string, isDefault = false): Credential {
  return {
    id: `cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f02${name.length}` as Credential['id'],
    name,
    kind: 'model',
    provider: 'openai',
    protocol: 'openai_responses',
    model: 'gpt-5',
    compatible_engine_ids: ['codex'],
    is_default: isDefault,
    data: { OPENAI_API_KEY: 'sk-test' },
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  }
}

describe('selectInitialModelConnection', () => {
  it('selects a single option or a unique default only', () => {
    expect(selectInitialModelConnection([credential('only')])).toBe(
      'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f024',
    )
    expect(
      selectInitialModelConnection([credential('a'), credential('default', true), credential('b')]),
    ).toBe('cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f027')
    expect(selectInitialModelConnection([credential('a'), credential('b')])).toBe('')
    expect(selectInitialModelConnection([credential('a', true), credential('b', true)])).toBe('')
  })
})

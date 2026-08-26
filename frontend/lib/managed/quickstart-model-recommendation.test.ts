import { describe, expect, it } from 'vitest'

import type { LlmEngineCapability } from '@/types/llm'
import type { Credential } from '@/types/managed'

import { recommendQuickstartModelConnection } from './quickstart-model-recommendation'

const engine: LlmEngineCapability = {
  id: 'native',
  display_name: 'Native',
  enabled: true,
  supported_protocol_ids: ['openai_responses', 'anthropic_messages'],
  preferred_protocol_ids: ['openai_responses'],
}

function credential(
  id: string,
  patch: Partial<Pick<Credential, 'protocol' | 'is_default' | 'created_at' | 'archived_at'>> = {},
): Credential {
  return {
    id: `cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f0${id}` as Credential['id'],
    name: `connection-${id}`,
    kind: 'model',
    provider: 'openai',
    protocol: patch.protocol ?? 'openai_responses',
    model: 'gpt-5',
    compatible_engine_ids: ['native'],
    is_default: patch.is_default ?? false,
    data: {},
    archived_at: patch.archived_at ?? null,
    created_at: patch.created_at ?? '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  }
}

describe('recommendQuickstartModelConnection', () => {
  it('auto-continues with the only active compatible connection', () => {
    const recommendation = recommendQuickstartModelConnection(
      [credential('1'), credential('2', { archived_at: '2026-08-02T00:00:00Z' })],
      engine,
    )

    expect(recommendation?.credential.name).toBe('connection-1')
    expect(recommendation?.reason).toBe('onlyCompatible')
    expect(recommendation?.autoContinue).toBe(true)
  })

  it('prefers a default on the engine preferred protocol when multiple defaults exist', () => {
    const recommendation = recommendQuickstartModelConnection(
      [
        credential('1', {
          protocol: 'anthropic_messages',
          is_default: true,
          created_at: '2026-08-03T00:00:00Z',
        }),
        credential('2', {
          protocol: 'openai_responses',
          is_default: true,
          created_at: '2026-08-01T00:00:00Z',
        }),
      ],
      engine,
    )

    expect(recommendation?.credential.name).toBe('connection-2')
    expect(recommendation?.reason).toBe('preferredProtocolDefault')
    expect(recommendation?.autoContinue).toBe(true)
  })

  it('selects but waits for confirmation when falling back to a non-default preferred protocol', () => {
    const recommendation = recommendQuickstartModelConnection(
      [
        credential('1', {
          protocol: 'anthropic_messages',
          created_at: '2026-08-03T00:00:00Z',
        }),
        credential('2', {
          protocol: 'openai_responses',
          created_at: '2026-08-01T00:00:00Z',
        }),
      ],
      engine,
    )

    expect(recommendation?.credential.name).toBe('connection-2')
    expect(recommendation?.reason).toBe('preferredProtocol')
    expect(recommendation?.autoContinue).toBe(false)
  })
})

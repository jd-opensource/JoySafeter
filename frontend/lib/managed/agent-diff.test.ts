import { describe, expect, it } from 'vitest'

import type { Agent, ModelConnectionSummary } from '@/types/managed'

import { diffAgents } from './agent-diff'

const agent = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001',
    name: 'Agent',
    engine_kind: 'claude',
    model: null,
    model_credential_id: null,
    created_at: '2026-08-27T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
    ...overrides,
  }) as Agent

const connection = (id: string, overrides: Partial<ModelConnectionSummary> = {}) =>
  ({
    id,
    name: 'Production model',
    provider: 'anthropic',
    protocol: 'anthropic_messages',
    model: 'claude-sonnet-4-5',
    is_default: false,
    archived_at: null,
    ...overrides,
  }) as ModelConnectionSummary

describe('agent model diff', () => {
  it('compares canonical model connections when legacy models are null', () => {
    const beforeId = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f002'
    const afterId = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f003'
    const diff = diffAgents(
      agent({ model_credential_id: beforeId, model_connection: connection(beforeId) }),
      agent({
        model_credential_id: afterId,
        model_connection: connection(afterId, { provider: 'openai', model: 'gpt-5' }),
      }),
    )

    expect(diff.model.changed).toBe(true)
    expect(diff.model.changedKeys).toContain('model_credential_id')
    expect(diff.model.after).toMatchObject({ model_credential_id: afterId, model: 'gpt-5' })
  })

  it('falls back to canonical connection ids when summaries are unavailable', () => {
    const beforeId = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f002'
    const afterId = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f003'
    const diff = diffAgents(
      agent({ model_credential_id: beforeId }),
      agent({ model_credential_id: afterId }),
    )

    expect(diff.model.changed).toBe(true)
    expect(diff.model.before).toMatchObject({ model_credential_id: beforeId })
    expect(diff.model.after).toMatchObject({ model_credential_id: afterId })
  })
})

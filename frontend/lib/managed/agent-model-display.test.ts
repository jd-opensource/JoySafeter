import { describe, expect, it } from 'vitest'

import type { Agent, ModelConnectionSummary } from '@/types/managed'

import { getAgentModelDisplayState } from './agent-model-display'

const agent = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001',
    name: 'Agent',
    engine_kind: 'claude',
    model: null,
    version: 1,
    model_credential_id: null,
    created_at: '2026-08-19T00:00:00Z',
    updated_at: '2026-08-19T00:00:00Z',
    ...overrides,
  }) as Agent

const modelConnection = (overrides: Partial<ModelConnectionSummary> = {}): ModelConnectionSummary =>
  ({
    id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f002',
    name: 'Anthropic Prod',
    provider: 'anthropic',
    protocol: 'anthropic_messages',
    model: 'claude-sonnet-4-5',
    is_default: true,
    archived_at: null,
    ...overrides,
  }) as ModelConnectionSummary

describe('agent model display state', () => {
  it('uses the bound model connection as the only model display source', () => {
    expect(
      getAgentModelDisplayState(
        agent({
          model: { id: 'claude-opus-4-1' },
          model_credential_id: modelConnection().id,
          model_connection: modelConnection(),
        }),
      ),
    ).toMatchObject({ kind: 'connection', modelLabel: 'Anthropic Prod' })
  })

  it('falls back to the connection model when the connection has no name', () => {
    expect(
      getAgentModelDisplayState(
        agent({
          model_credential_id: modelConnection().id,
          model_connection: modelConnection({ name: '', model: 'claude-sonnet-4-5' }),
        }),
      ),
    ).toMatchObject({ kind: 'connection', modelLabel: 'claude-sonnet-4-5' })
  })

  it('distinguishes unavailable and unbound states', () => {
    const boundAgent = agent({ model_credential_id: modelConnection().id })
    expect(getAgentModelDisplayState(boundAgent)).toMatchObject({ kind: 'connection_unavailable' })
    expect(getAgentModelDisplayState(agent())).toMatchObject({ kind: 'unbound' })
  })
})

import { describe, expect, it } from 'vitest'

import { parseAgentResponse } from './agent-response-parsers'

const AGENT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'
const SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f002'
const CREDENTIAL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f003'

function rawAgent() {
  return {
    id: `agent_${AGENT_UUID}`,
    name: 'Agent',
    engine_kind: 'claude',
    model: { id: 'model' },
    model_credential_id: `cred_${CREDENTIAL_UUID}`,
    model_connection: {
      id: `cred_${CREDENTIAL_UUID}`,
      name: 'Anthropic Prod',
      provider: 'anthropic',
      protocol: 'anthropic_messages',
      model: 'claude-sonnet-4-5',
      is_default: true,
      archived_at: null,
    },
    skills: [{ type: 'custom' as const, skill_id: `skill_${SKILL_UUID}`, version: '1.0.0' }],
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  }
}

describe('agent response parsers', () => {
  it('validates root and nested skill identities', () => {
    const agent = parseAgentResponse(rawAgent())
    expect(agent.id).toBe(`agent_${AGENT_UUID}`)
    expect(agent.model_connection?.id).toBe(`cred_${CREDENTIAL_UUID}`)
    expect(agent.skills?.[0].skill_id).toBe(`skill_${SKILL_UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseAgentResponse({ ...rawAgent(), id: AGENT_UUID })).toThrow()
    expect(() =>
      parseAgentResponse({
        ...rawAgent(),
        skills: [{ type: 'custom', skill_id: `agent_${SKILL_UUID}`, version: '1.0.0' }],
      }),
    ).toThrow()
  })

  it('rejects missing or blank engine identity instead of guessing a default', () => {
    expect(() => parseAgentResponse({ ...rawAgent(), engine_kind: undefined })).toThrow(
      /engine_kind/,
    )
    expect(() => parseAgentResponse({ ...rawAgent(), engine_kind: '   ' })).toThrow(/engine_kind/)
  })

  it('rejects legacy string model responses', () => {
    expect(() => parseAgentResponse({ ...rawAgent(), model: 'claude-sonnet-4-5' })).toThrow(
      /Invalid agent model/,
    )
  })
})

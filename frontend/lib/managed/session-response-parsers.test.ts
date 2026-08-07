import { describe, expect, it } from 'vitest'

import { parseSessionResponse } from './session-response-parsers'

const SESSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'
const AGENT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f002'
const VAULT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f003'
const RESOURCE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f004'

function rawSession() {
  return {
    id: `sess_${SESSION_UUID}`,
    agent: { id: `agent_${AGENT_UUID}`, agent_id: `agent_${AGENT_UUID}`, name: 'Agent' },
    status: 'idle' as const,
    vault_ids: [`vault_${VAULT_UUID}`],
    repo_resources: [
      {
        id: `sesrsc_${RESOURCE_UUID}`,
        type: 'github_repository' as const,
        url: 'https://example.com/repo.git',
        branch: 'main',
        mount_path: '/workspace/repo',
        mount_name: 'repo',
      },
    ],
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  }
}

describe('session response parsers', () => {
  it('validates nested session identities', () => {
    const session = parseSessionResponse(rawSession())
    expect(session.id).toBe(`sess_${SESSION_UUID}`)
    expect(session.agent?.id).toBe(`agent_${AGENT_UUID}`)
    expect(session.vault_ids?.[0]).toBe(`vault_${VAULT_UUID}`)
    expect(session.repo_resources?.[0].id).toBe(`sesrsc_${RESOURCE_UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseSessionResponse({ ...rawSession(), id: SESSION_UUID })).toThrow()
    expect(() =>
      parseSessionResponse({ ...rawSession(), agent: { id: `task_${AGENT_UUID}`, name: 'Agent' } }),
    ).toThrow()
  })
})

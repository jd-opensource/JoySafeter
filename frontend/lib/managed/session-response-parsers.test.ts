import { describe, expect, it } from 'vitest'

import { parseSessionResponse } from './session-response-parsers'

const SESSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'
const AGENT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f002'
const GROUP_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f003'
const RESOURCE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f004'
const CREDENTIAL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f005'

function rawSession() {
  return {
    id: `sess_${SESSION_UUID}`,
    agent: {
      id: `agent_${AGENT_UUID}`,
      agent_id: `agent_${AGENT_UUID}`,
      name: 'Agent',
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
    },
    status: 'idle' as const,
    credential_group_ids: [`credgrp_${GROUP_UUID}`],
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
    storage_mounts: [
      {
        id: `sesrsc_${RESOURCE_UUID}`,
        type: 'storage' as const,
        name: 'datasets',
        volume_ref: 'datasets',
        volume_id: `vol_${RESOURCE_UUID}`,
        sub_path: '',
        mount_path: '/mnt/datasets',
        access: 'read_only',
        required: true,
        created_at: '2026-08-07T00:00:00Z',
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
    expect(session.agent?.model_credential_id).toBe(`cred_${CREDENTIAL_UUID}`)
    expect(session.agent?.model_connection?.id).toBe(`cred_${CREDENTIAL_UUID}`)
    expect(session.credential_group_ids?.[0]).toBe(`credgrp_${GROUP_UUID}`)
    expect(session.repo_resources?.[0].id).toBe(`sesrsc_${RESOURCE_UUID}`)
    expect(session.storage_mounts?.[0].id).toBe(`sesrsc_${RESOURCE_UUID}`)
    expect(session.storage_mounts?.[0].volume_id).toBe(`vol_${RESOURCE_UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseSessionResponse({ ...rawSession(), id: SESSION_UUID })).toThrow()
    expect(() =>
      parseSessionResponse({ ...rawSession(), agent: { id: `task_${AGENT_UUID}`, name: 'Agent' } }),
    ).toThrow()
    expect(() =>
      parseSessionResponse({
        ...rawSession(),
        storage_mounts: [{ ...rawSession().storage_mounts[0], volume_id: RESOURCE_UUID }],
      }),
    ).toThrow()
  })

  it('rejects legacy string model responses inside session agents', () => {
    expect(() =>
      parseSessionResponse({
        ...rawSession(),
        agent: { ...rawSession().agent, model: 'claude-sonnet-4-5' },
      }),
    ).toThrow(/Invalid agent model/)
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import { ORGANIZATION_ID, OTHER_VAULT_ID, PROJECT_ID, VAULT_ID } from '@/test-utils/entity-ids'

import {
  fetchManagedCredentialGroup,
  fetchManagedCredentialGroupMembers,
  fetchManagedCredentialGroupOptions,
  fetchManagedCredentialGroups,
  managedCredentialGroupMembersQueryKey,
  managedCredentialGroupOptionsQueryKey,
  managedCredentialGroupQueryKey,
} from './credential-group-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

function rawCredentialGroup(id: string, archivedAt: string | null = null) {
  return {
    id,
    name: id === VAULT_ID ? 'Primary' : 'Secondary',
    archived_at: archivedAt,
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
  }
}

describe('managed Credential Group client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns typed paginated Credential Group transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawCredentialGroup(VAULT_ID)],
      has_more: false,
      first_id: VAULT_ID,
      last_id: VAULT_ID,
    })

    await expect(
      fetchManagedCredentialGroups(
        { limit: 25, afterId: OTHER_VAULT_ID, includeArchived: true },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: VAULT_ID, name: 'Primary' })],
      hasMore: false,
      firstId: VAULT_ID,
      lastId: VAULT_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/credential-groups?limit=25&after_id=${OTHER_VAULT_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every active option page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawCredentialGroup(VAULT_ID)],
        has_more: true,
        first_id: VAULT_ID,
        last_id: VAULT_ID,
      })
      .mockResolvedValueOnce({
        data: [rawCredentialGroup(OTHER_VAULT_ID, '2026-09-03T01:00:00Z')],
        has_more: false,
        first_id: OTHER_VAULT_ID,
        last_id: OTHER_VAULT_ID,
      })

    expect(managedCredentialGroupOptionsQueryKey(requestScope.key)).toEqual([
      'credential-groups',
      requestScope.key,
      'options',
      false,
    ])
    await expect(fetchManagedCredentialGroupOptions(requestScope)).resolves.toEqual([
      expect.objectContaining({ id: VAULT_ID, name: 'Primary' }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/credential-groups?limit=100&after_id=${VAULT_ID}&include_archived=false`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical list responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([rawCredentialGroup(VAULT_ID)])
    await expect(fetchManagedCredentialGroups({}, requestScope)).rejects.toThrow(
      /Credential Group list response/,
    )
  })

  it('owns Credential Group detail and non-paginated member transport', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce(rawCredentialGroup(VAULT_ID))
      .mockResolvedValueOnce({
        data: [
          {
            id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f130',
            group_id: VAULT_ID,
            kind: 'mcp',
            name: 'GitHub',
            provider: '',
            protocol: '',
            model: '',
            compatible_engine_ids: [],
            is_default: false,
            mcp_server_url: 'https://mcp.example.test',
            auth_scheme: 'static_bearer',
            created_at: '2026-09-03T00:00:00Z',
            updated_at: '2026-09-03T00:00:00Z',
            archived_at: null,
          },
        ],
      })

    expect(managedCredentialGroupQueryKey(requestScope.key, VAULT_ID)).toEqual([
      'credential-group',
      requestScope.key,
      VAULT_ID,
    ])
    expect(managedCredentialGroupMembersQueryKey(requestScope.key, VAULT_ID, false)).toEqual([
      'credential-group-members',
      requestScope.key,
      VAULT_ID,
      false,
    ])
    await expect(fetchManagedCredentialGroup(VAULT_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: VAULT_ID }),
    )
    await expect(
      fetchManagedCredentialGroupMembers(VAULT_ID, false, requestScope),
    ).resolves.toEqual([expect.objectContaining({ group_id: VAULT_ID, name: 'GitHub' })])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/credential-groups/${VAULT_ID}/members?include_archived=false`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects a paginated or malformed member envelope', async () => {
    vi.mocked(managedGet).mockResolvedValue([])
    await expect(fetchManagedCredentialGroupMembers(VAULT_ID, false, requestScope)).rejects.toThrow(
      /Credential Group members response/,
    )
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import { AGENT_ID, ORGANIZATION_ID, OTHER_AGENT_ID, PROJECT_ID } from '@/test-utils/entity-ids'
import { parseAgentVersionId } from '@/types/entity-id'

import {
  fetchManagedAgent,
  fetchManagedAgentOptions,
  fetchManagedAgentVersionHistory,
  fetchManagedAgentVersions,
  fetchManagedAgents,
  managedAgentOptionsQueryKey,
  managedAgentQueryKey,
  managedAgentVersionsQueryKey,
} from './agent-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}
const AGENT_VERSION_ID = parseAgentVersionId('agentver_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120')
const OTHER_AGENT_VERSION_ID = parseAgentVersionId('agentver_018f6f42-0a51-7cc4-98c8-4f6f0ca5f121')

function rawAgent(id: string, archivedAt: string | null = null) {
  return {
    id,
    name: id === AGENT_ID ? 'Primary' : 'Secondary',
    engine_kind: 'claude',
    archived_at: archivedAt,
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
  }
}

function rawAgentVersion(id: string, version: number) {
  return {
    id,
    agent_id: AGENT_ID,
    version,
    snapshot: rawAgent(AGENT_ID),
    created_at: '2026-09-03T00:00:00Z',
  }
}

describe('managed Agent client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns typed paginated Agent transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawAgent(AGENT_ID)],
      has_more: false,
      first_id: AGENT_ID,
      last_id: AGENT_ID,
    })

    await expect(
      fetchManagedAgents(
        { limit: 25, afterId: OTHER_AGENT_ID, includeArchived: true },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: AGENT_ID, name: 'Primary' })],
      hasMore: false,
      firstId: AGENT_ID,
      lastId: AGENT_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/agents?limit=25&after_id=${OTHER_AGENT_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every active option page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawAgent(AGENT_ID)],
        has_more: true,
        first_id: AGENT_ID,
        last_id: AGENT_ID,
      })
      .mockResolvedValueOnce({
        data: [rawAgent(OTHER_AGENT_ID, '2026-09-03T01:00:00Z')],
        has_more: false,
        first_id: OTHER_AGENT_ID,
        last_id: OTHER_AGENT_ID,
      })

    expect(managedAgentOptionsQueryKey(requestScope.key)).toEqual([
      'agents',
      requestScope.key,
      'options',
      false,
    ])
    await expect(fetchManagedAgentOptions(requestScope)).resolves.toEqual([
      expect.objectContaining({ id: AGENT_ID, name: 'Primary' }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/agents?limit=100&after_id=${AGENT_ID}&include_archived=false`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical list responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([rawAgent(AGENT_ID)])
    await expect(fetchManagedAgents({}, requestScope)).rejects.toThrow(/Agent list response/)
  })

  it('owns Agent detail transport and cache identity', async () => {
    vi.mocked(managedGet).mockResolvedValue(rawAgent(AGENT_ID))

    expect(managedAgentQueryKey(requestScope.key, AGENT_ID)).toEqual([
      'agent',
      requestScope.key,
      AGENT_ID,
    ])
    await expect(fetchManagedAgent(AGENT_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: AGENT_ID, name: 'Primary' }),
    )
    expect(managedGet).toHaveBeenCalledWith(
      `/agents/${AGENT_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects complete Agent version history with the numeric version cursor', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawAgentVersion(AGENT_VERSION_ID, 101)],
        has_more: true,
      })
      .mockResolvedValueOnce({
        data: [rawAgentVersion(OTHER_AGENT_VERSION_ID, 100)],
        has_more: false,
      })

    expect(managedAgentVersionsQueryKey(requestScope.key, AGENT_ID)).toEqual([
      'agent-versions',
      requestScope.key,
      AGENT_ID,
    ])
    await expect(fetchManagedAgentVersionHistory(AGENT_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: AGENT_VERSION_ID, version: 101 }),
      expect.objectContaining({ id: OTHER_AGENT_VERSION_ID, version: 100 }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/agents/${AGENT_ID}/versions?limit=100&before_version=101`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed or non-advancing Agent version pages', async () => {
    vi.mocked(managedGet).mockResolvedValueOnce({ data: [] })
    await expect(fetchManagedAgentVersions(AGENT_ID, {}, requestScope)).rejects.toThrow(
      /Agent version list response/,
    )

    vi.mocked(managedGet).mockResolvedValue({ data: [], has_more: true })
    await expect(fetchManagedAgentVersionHistory(AGENT_ID, requestScope)).rejects.toThrow(
      /invalid cursor/,
    )
  })
})

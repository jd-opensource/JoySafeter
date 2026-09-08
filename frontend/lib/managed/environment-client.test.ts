import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import {
  ENVIRONMENT_ID,
  ORGANIZATION_ID,
  OTHER_ENVIRONMENT_ID,
  PROJECT_ID,
} from '@/test-utils/entity-ids'

import {
  fetchManagedEnvironment,
  fetchManagedEnvironmentOptions,
  fetchManagedEnvironments,
  managedEnvironmentOptionsQueryKey,
  managedEnvironmentQueryKey,
} from './environment-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

function rawEnvironment(id: string, archivedAt: string | null = null) {
  return {
    id,
    name: id === ENVIRONMENT_ID ? 'Primary' : 'Secondary',
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
    archived_at: archivedAt,
  }
}

describe('managed Environment options client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns the canonical active-options query identity', () => {
    expect(managedEnvironmentOptionsQueryKey(requestScope.key)).toEqual([
      'environments',
      requestScope.key,
      'options',
      false,
    ])
  })

  it('collects all pages, validates typed ids, and excludes archived records', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawEnvironment(ENVIRONMENT_ID)],
        has_more: true,
        first_id: ENVIRONMENT_ID,
        last_id: ENVIRONMENT_ID,
      })
      .mockResolvedValueOnce({
        data: [rawEnvironment(OTHER_ENVIRONMENT_ID, '2026-09-03T01:00:00Z')],
        has_more: false,
        first_id: OTHER_ENVIRONMENT_ID,
        last_id: OTHER_ENVIRONMENT_ID,
      })

    await expect(fetchManagedEnvironmentOptions(requestScope)).resolves.toEqual([
      expect.objectContaining({ id: ENVIRONMENT_ID, name: 'Primary' }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      1,
      '/environments?limit=100&include_archived=false',
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/environments?limit=100&after_id=${ENVIRONMENT_ID}&include_archived=false`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns typed paginated Environment transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawEnvironment(ENVIRONMENT_ID)],
      has_more: false,
      first_id: ENVIRONMENT_ID,
      last_id: ENVIRONMENT_ID,
    })

    await expect(
      fetchManagedEnvironments(
        { limit: 25, afterId: OTHER_ENVIRONMENT_ID, includeArchived: true },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: ENVIRONMENT_ID, name: 'Primary' })],
      hasMore: false,
      firstId: ENVIRONMENT_ID,
      lastId: ENVIRONMENT_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/environments?limit=25&after_id=${OTHER_ENVIRONMENT_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed envelopes and cross-entity ids', async () => {
    vi.mocked(managedGet).mockResolvedValueOnce({ data: [] })
    await expect(fetchManagedEnvironmentOptions(requestScope)).rejects.toThrow(
      /Environment list response/,
    )

    vi.mocked(managedGet).mockResolvedValueOnce({
      data: [rawEnvironment('agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001')],
      has_more: false,
      first_id: null,
      last_id: null,
    })
    await expect(fetchManagedEnvironmentOptions(requestScope)).rejects.toThrow()
  })

  it('owns Environment detail transport and cache identity', async () => {
    vi.mocked(managedGet).mockResolvedValue(rawEnvironment(ENVIRONMENT_ID))

    expect(managedEnvironmentQueryKey(requestScope.key, ENVIRONMENT_ID)).toEqual([
      'environment',
      requestScope.key,
      ENVIRONMENT_ID,
    ])
    await expect(fetchManagedEnvironment(ENVIRONMENT_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: ENVIRONMENT_ID, name: 'Primary' }),
    )
    expect(managedGet).toHaveBeenCalledWith(
      `/environments/${ENVIRONMENT_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })
})

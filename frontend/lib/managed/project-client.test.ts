import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import { ORGANIZATION_ID, OTHER_PROJECT_ID, PROJECT_ID } from '@/test-utils/entity-ids'

import {
  fetchManagedProject,
  fetchManagedProjectOptions,
  fetchManagedOrganizationProjectOptions,
  fetchManagedProjects,
  managedProjectOptionsQueryKey,
  managedProjectQueryKey,
} from './project-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

function rawProject(id: string) {
  return {
    id,
    org_id: ORGANIZATION_ID,
    name: id === PROJECT_ID ? 'Primary' : 'Secondary',
    slug: id === PROJECT_ID ? 'primary' : 'secondary',
    is_default: id === PROJECT_ID,
    archived_at: null,
    capability: 'admin',
    project_role: 'admin',
    created_at: '2026-09-03T00:00:00Z',
  }
}

describe('managed Project client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns typed paginated Project transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawProject(PROJECT_ID)],
      has_more: false,
      first_id: PROJECT_ID,
      last_id: PROJECT_ID,
    })

    await expect(
      fetchManagedProjects(
        { limit: 25, afterId: OTHER_PROJECT_ID, includeArchived: true },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: PROJECT_ID, created_at: '2026-09-03T00:00:00Z' })],
      hasMore: false,
      firstId: PROJECT_ID,
      lastId: PROJECT_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/auth/projects?limit=25&after_id=${OTHER_PROJECT_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Project detail transport and organization-scoped identity', async () => {
    vi.mocked(managedGet).mockResolvedValue(rawProject(PROJECT_ID))

    expect(managedProjectQueryKey(ORGANIZATION_ID, PROJECT_ID)).toEqual([
      'project',
      ORGANIZATION_ID,
      PROJECT_ID,
    ])
    await expect(fetchManagedProject(PROJECT_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: PROJECT_ID, name: 'Primary' }),
    )
    expect(managedGet).toHaveBeenCalledWith(
      `/auth/projects/${PROJECT_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every active Project option page under the organization identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawProject(PROJECT_ID)],
        has_more: true,
        first_id: PROJECT_ID,
        last_id: PROJECT_ID,
      })
      .mockResolvedValueOnce({
        data: [rawProject(OTHER_PROJECT_ID)],
        has_more: false,
        first_id: OTHER_PROJECT_ID,
        last_id: OTHER_PROJECT_ID,
      })

    expect(managedProjectOptionsQueryKey(ORGANIZATION_ID)).toEqual([
      'projects',
      ORGANIZATION_ID,
      'options',
      false,
    ])
    await expect(fetchManagedProjectOptions(requestScope)).resolves.toHaveLength(2)
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/auth/projects?limit=200&after_id=${PROJECT_ID}&include_archived=false`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed pagination envelopes', async () => {
    vi.mocked(managedGet).mockResolvedValue({ data: [rawProject(PROJECT_ID)] })
    await expect(fetchManagedProjects({}, requestScope)).rejects.toThrow(/Project list response/)
  })

  it('loads another organization through the same complete catalog boundary', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawProject(OTHER_PROJECT_ID)],
      has_more: false,
      first_id: OTHER_PROJECT_ID,
      last_id: OTHER_PROJECT_ID,
    })

    await expect(fetchManagedOrganizationProjectOptions(ORGANIZATION_ID)).resolves.toHaveLength(1)
    expect(managedGet).toHaveBeenCalledWith('/auth/projects?limit=200&include_archived=false', {
      headers: { 'X-Org-Id': ORGANIZATION_ID },
      skipManagedContext: true,
    })
  })
})

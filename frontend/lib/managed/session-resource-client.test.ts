import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import {
  FILE_ID,
  ORGANIZATION_ID,
  PROJECT_ID,
  SESSION_ID,
  SESSION_RESOURCE_ID,
} from '@/test-utils/entity-ids'

import {
  addManagedSessionFileResource,
  addManagedSessionRepositoryResource,
  fetchManagedSessionResources,
  managedSessionResourcesQueryKey,
  removeManagedSessionResource,
  rotateManagedSessionRepositoryToken,
} from './session-resource-client'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
}))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}
const requestOptions = {
  headers: {
    'X-Org-Id': ORGANIZATION_ID,
    'X-Project-Id': PROJECT_ID,
  },
  skipManagedContext: true,
}

describe('managed Session resource client', () => {
  beforeEach(() => {
    vi.mocked(managedDelete).mockReset()
    vi.mocked(managedGet).mockReset()
    vi.mocked(managedPatch).mockReset()
    vi.mocked(managedPost).mockReset()
  })

  it('owns the scoped resource query and parses typed resource ids', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [
        {
          id: SESSION_RESOURCE_ID,
          type: 'file',
          file_id: FILE_ID,
          mount_path: '/workspace/report.md',
          access: 'read_only',
          created_at: '2026-09-03T00:00:00Z',
        },
      ],
    })

    expect(managedSessionResourcesQueryKey(requestScope.key, SESSION_ID)).toEqual([
      'session-resources',
      requestScope.key,
      SESSION_ID,
    ])
    await expect(fetchManagedSessionResources(SESSION_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SESSION_RESOURCE_ID, file_id: FILE_ID }),
    ])
    expect(managedGet).toHaveBeenCalledWith(`/sessions/${SESSION_ID}/resources`, requestOptions)
  })

  it('serializes file and repository attachments through one resource boundary', async () => {
    vi.mocked(managedPost)
      .mockResolvedValueOnce({
        id: SESSION_RESOURCE_ID,
        type: 'file',
        file_id: FILE_ID,
      })
      .mockResolvedValueOnce({ id: SESSION_RESOURCE_ID, type: 'github_repository' })

    await addManagedSessionFileResource(
      SESSION_ID,
      { fileId: FILE_ID, mountPath: '/workspace/report.md' },
      requestScope,
    )
    await addManagedSessionRepositoryResource(
      SESSION_ID,
      {
        url: 'https://github.com/example/project.git',
        branch: 'main',
        authorizationToken: 'token',
      },
      requestScope,
    )

    expect(managedPost).toHaveBeenNthCalledWith(
      1,
      `/sessions/${SESSION_ID}/resources`,
      { type: 'file', file_id: FILE_ID, mount_path: '/workspace/report.md' },
      requestOptions,
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      2,
      `/sessions/${SESSION_ID}/resources`,
      {
        type: 'github_repository',
        url: 'https://github.com/example/project.git',
        branch: 'main',
        authorization_token: 'token',
      },
      requestOptions,
    )
  })

  it('validates resource deletion and repository-token rotation responses', async () => {
    vi.mocked(managedDelete).mockResolvedValue({ id: SESSION_RESOURCE_ID, deleted: true })
    vi.mocked(managedPatch).mockResolvedValue({
      id: SESSION_RESOURCE_ID,
      type: 'github_repository',
    })

    await expect(
      removeManagedSessionResource(SESSION_ID, SESSION_RESOURCE_ID, requestScope),
    ).resolves.toBe(SESSION_RESOURCE_ID)
    await rotateManagedSessionRepositoryToken(
      SESSION_ID,
      SESSION_RESOURCE_ID,
      { authorizationToken: 'rotated-token' },
      requestScope,
    )

    expect(managedPatch).toHaveBeenCalledWith(
      `/sessions/${SESSION_ID}/resources/${SESSION_RESOURCE_ID}`,
      { authorization_token: 'rotated-token' },
      requestOptions,
    )
  })

  it('rejects a deletion response for a different resource', async () => {
    vi.mocked(managedDelete).mockResolvedValue({
      id: 'sesrsc_018f6f42-0a51-7cc4-98c8-4f6f0ca5f099',
      deleted: true,
    })

    await expect(
      removeManagedSessionResource(SESSION_ID, SESSION_RESOURCE_ID, requestScope),
    ).rejects.toThrow(/Mismatched deleted session resource id/)
  })
})

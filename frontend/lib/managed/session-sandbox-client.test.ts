import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedFetchResponse, managedGet } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID, SESSION_ID } from '@/test-utils/entity-ids'

import {
  fetchManagedSessionSandboxDownload,
  fetchManagedSessionSandboxFileContent,
  fetchManagedSessionSandboxFiles,
  managedSessionSandboxFileContentQueryKey,
  managedSessionSandboxFilesQueryKey,
} from './session-sandbox-client'

vi.mock('@/lib/api-client', () => ({
  managedFetchResponse: vi.fn(),
  managedGet: vi.fn(),
}))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

describe('managed Session sandbox client', () => {
  beforeEach(() => {
    vi.mocked(managedFetchResponse).mockReset()
    vi.mocked(managedGet).mockReset()
  })

  it('uses the backend type field for sandbox directory entries', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      ok: true,
      code: '',
      error: '',
      path: '/workspace',
      entries: [{ name: 'src', path: '/workspace/src', type: 'directory', size: 0, mtime: 1 }],
    })

    await expect(
      fetchManagedSessionSandboxFiles(SESSION_ID, '/workspace', requestScope),
    ).resolves.toEqual({
      path: '/workspace',
      entries: [{ name: 'src', path: '/workspace/src', type: 'directory', size: 0, mtime: 1 }],
    })
    expect(managedSessionSandboxFilesQueryKey(requestScope.key, SESSION_ID, '/workspace')).toEqual([
      'session-sandbox-files',
      requestScope.key,
      SESSION_ID,
      '/workspace',
    ])
  })

  it('rejects the obsolete file_type response shape', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      path: '/workspace',
      entries: [{ name: 'src', path: '/workspace/src', file_type: 'directory', size: 0, mtime: 1 }],
    })

    await expect(
      fetchManagedSessionSandboxFiles(SESSION_ID, '/workspace', requestScope),
    ).rejects.toThrow(/sandbox file entry/)
  })

  it('owns content and binary download paths', async () => {
    const response = new Response('archive')
    vi.mocked(managedGet).mockResolvedValue({ path: '/workspace/readme.md', content: 'hello' })
    vi.mocked(managedFetchResponse).mockResolvedValue(response)

    expect(
      managedSessionSandboxFileContentQueryKey(
        requestScope.key,
        SESSION_ID,
        '/workspace/readme.md',
      ),
    ).toEqual([
      'session-sandbox-file-content',
      requestScope.key,
      SESSION_ID,
      '/workspace/readme.md',
    ])
    await expect(
      fetchManagedSessionSandboxFileContent(SESSION_ID, '/workspace/readme.md', requestScope),
    ).resolves.toMatchObject({ content: 'hello' })
    await expect(
      fetchManagedSessionSandboxDownload(SESSION_ID, '/workspace', requestScope, {
        archive: true,
      }),
    ).resolves.toBe(response)

    expect(managedFetchResponse).toHaveBeenCalledWith(
      `/sessions/${SESSION_ID}/sandbox/files/archive?path=%2Fworkspace`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed sandbox content responses', async () => {
    vi.mocked(managedGet).mockResolvedValue({ path: '/workspace/readme.md', content: 42 })

    await expect(
      fetchManagedSessionSandboxFileContent(SESSION_ID, '/workspace/readme.md', requestScope),
    ).rejects.toThrow(/sandbox file content response/)
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID } from '@/test-utils/entity-ids'
import { parseFileId } from '@/types/entity-id'

import {
  fetchManagedFileOptions,
  fetchManagedFiles,
  managedFileOptionsQueryKey,
} from './file-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const FILE_ID = parseFileId('file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120')
const OTHER_FILE_ID = parseFileId('file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f121')
const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

function rawFile(id: string) {
  return {
    id,
    filename: id === FILE_ID ? 'primary.txt' : 'secondary.txt',
    purpose: 'assistants',
    content_type: 'text/plain',
    size_bytes: 10,
    downloadable: true,
    created_at: '2026-09-03T00:00:00Z',
  }
}

describe('managed File client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns typed paginated File transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawFile(FILE_ID)],
      has_more: false,
      first_id: FILE_ID,
      last_id: FILE_ID,
    })

    await expect(
      fetchManagedFiles({ limit: 25, afterId: OTHER_FILE_ID }, requestScope),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: FILE_ID, filename: 'primary.txt' })],
      hasMore: false,
      firstId: FILE_ID,
      lastId: FILE_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/files?limit=25&after_id=${OTHER_FILE_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every File option page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawFile(FILE_ID)],
        has_more: true,
        first_id: FILE_ID,
        last_id: FILE_ID,
      })
      .mockResolvedValueOnce({
        data: [rawFile(OTHER_FILE_ID)],
        has_more: false,
        first_id: OTHER_FILE_ID,
        last_id: OTHER_FILE_ID,
      })

    expect(managedFileOptionsQueryKey(requestScope.key)).toEqual([
      'files',
      requestScope.key,
      'options',
    ])
    await expect(fetchManagedFileOptions(requestScope)).resolves.toEqual([
      expect.objectContaining({ id: FILE_ID }),
      expect.objectContaining({ id: OTHER_FILE_ID }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/files?limit=100&after_id=${FILE_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical list responses', async () => {
    vi.mocked(managedGet).mockResolvedValue({ data: [rawFile(FILE_ID)] })
    await expect(fetchManagedFiles({}, requestScope)).rejects.toThrow(/File list response/)
  })
})

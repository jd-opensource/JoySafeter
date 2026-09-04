import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID } from '@/test-utils/entity-ids'
import { parseMemoryId, parseMemoryStoreId } from '@/types/entity-id'

import {
  fetchManagedMemories,
  fetchManagedMemoryDirectory,
  fetchManagedMemoryStoreOptions,
  fetchManagedMemoryStores,
  managedMemoryDirectoryQueryKey,
  managedMemoryStoreOptionsQueryKey,
} from './memory-store-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const MEMORY_STORE_ID = parseMemoryStoreId('memstore_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120')
const OTHER_MEMORY_STORE_ID = parseMemoryStoreId('memstore_018f6f42-0a51-7cc4-98c8-4f6f0ca5f121')
const MEMORY_ID = parseMemoryId('mem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122')
const OTHER_MEMORY_ID = parseMemoryId('mem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f123')
const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

function rawMemoryStore(id: string, archivedAt: string | null = null) {
  return {
    id,
    name: id === MEMORY_STORE_ID ? 'Primary' : 'Secondary',
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
    archived_at: archivedAt,
  }
}

function rawMemory(id: string, path: string) {
  return {
    id,
    memory_store_id: MEMORY_STORE_ID,
    path,
    content: path,
    content_size_bytes: path.length,
    metadata: {},
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
  }
}

describe('managed Memory Store client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns typed paginated Memory Store transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawMemoryStore(MEMORY_STORE_ID)],
      has_more: false,
      first_id: MEMORY_STORE_ID,
      last_id: MEMORY_STORE_ID,
    })

    await expect(
      fetchManagedMemoryStores(
        { limit: 25, afterId: OTHER_MEMORY_STORE_ID, includeArchived: true },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: MEMORY_STORE_ID, name: 'Primary' })],
      hasMore: false,
      firstId: MEMORY_STORE_ID,
      lastId: MEMORY_STORE_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/memory_stores?limit=25&after_id=${OTHER_MEMORY_STORE_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every active option page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawMemoryStore(MEMORY_STORE_ID)],
        has_more: true,
        first_id: MEMORY_STORE_ID,
        last_id: MEMORY_STORE_ID,
      })
      .mockResolvedValueOnce({
        data: [rawMemoryStore(OTHER_MEMORY_STORE_ID)],
        has_more: false,
        first_id: OTHER_MEMORY_STORE_ID,
        last_id: OTHER_MEMORY_STORE_ID,
      })

    expect(managedMemoryStoreOptionsQueryKey(requestScope.key)).toEqual([
      'memory-stores',
      requestScope.key,
      'options',
      false,
    ])
    await expect(fetchManagedMemoryStoreOptions(requestScope)).resolves.toEqual([
      expect.objectContaining({ id: MEMORY_STORE_ID }),
      expect.objectContaining({ id: OTHER_MEMORY_STORE_ID }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/memory_stores?limit=100&after_id=${MEMORY_STORE_ID}&include_archived=false`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('excludes archived records even if the service returns one', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawMemoryStore(MEMORY_STORE_ID, '2026-09-03T01:00:00Z')],
      has_more: false,
      first_id: MEMORY_STORE_ID,
      last_id: MEMORY_STORE_ID,
    })

    await expect(fetchManagedMemoryStoreOptions(requestScope)).resolves.toEqual([])
  })

  it('owns typed paginated Memory directory transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawMemory(MEMORY_ID, '/first.md')],
      has_more: false,
      first_id: MEMORY_ID,
      last_id: MEMORY_ID,
    })

    await expect(
      fetchManagedMemories(
        MEMORY_STORE_ID,
        { limit: 25, afterId: OTHER_MEMORY_ID, view: 'full' },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: MEMORY_ID, memory_store_id: MEMORY_STORE_ID })],
      hasMore: false,
      firstId: MEMORY_ID,
      lastId: MEMORY_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/memory_stores/${MEMORY_STORE_ID}/memories?limit=25&after_id=${OTHER_MEMORY_ID}&view=full`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every Memory directory page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawMemory(MEMORY_ID, '/first.md')],
        has_more: true,
        first_id: MEMORY_ID,
        last_id: MEMORY_ID,
      })
      .mockResolvedValueOnce({
        data: [rawMemory(OTHER_MEMORY_ID, '/second.md')],
        has_more: false,
        first_id: OTHER_MEMORY_ID,
        last_id: OTHER_MEMORY_ID,
      })

    expect(managedMemoryDirectoryQueryKey(requestScope.key, MEMORY_STORE_ID)).toEqual([
      'memory-stores',
      requestScope.key,
      MEMORY_STORE_ID,
      'memories',
      'full',
    ])
    await expect(fetchManagedMemoryDirectory(MEMORY_STORE_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: MEMORY_ID, path: '/first.md' }),
      expect.objectContaining({ id: OTHER_MEMORY_ID, path: '/second.md' }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/memory_stores/${MEMORY_STORE_ID}/memories?limit=100&after_id=${MEMORY_ID}&view=full`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical Memory directory responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([rawMemory(MEMORY_ID, '/first.md')])
    await expect(fetchManagedMemories(MEMORY_STORE_ID, {}, requestScope)).rejects.toThrow(
      /Memory directory response/,
    )
  })

  it('rejects Memory directory pagination that does not advance', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawMemory(MEMORY_ID, '/first.md')],
        has_more: true,
        first_id: MEMORY_ID,
        last_id: MEMORY_ID,
      })
      .mockResolvedValueOnce({
        data: [rawMemory(MEMORY_ID, '/first.md')],
        has_more: true,
        first_id: MEMORY_ID,
        last_id: MEMORY_ID,
      })

    await expect(fetchManagedMemoryDirectory(MEMORY_STORE_ID, requestScope)).rejects.toThrow(
      /Memory directory pagination returned an invalid cursor/,
    )
  })
})

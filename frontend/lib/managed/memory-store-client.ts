import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import {
  parseMemoryId,
  parseMemoryStoreId,
  type MemoryId,
  type MemoryStoreId,
} from '@/types/entity-id'
import type { MemoryStore } from '@/types/managed'

import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'
import {
  parseMemoryResponse,
  parseMemoryStoreResponse,
  type MemoryRecord,
} from './memory-response-parsers'

const MEMORY_STORE_OPTION_PAGE_SIZE = 100
const MEMORY_DIRECTORY_PAGE_SIZE = 100

export interface ManagedMemoryStorePageRequest {
  limit?: number
  afterId?: MemoryStoreId
  includeArchived?: boolean
}

export interface ManagedMemoryPageRequest {
  limit?: number
  afterId?: MemoryId
  view?: 'full'
}

export const MANAGED_MEMORY_STORES_QUERY_ROOT = 'memory-stores'
export const MANAGED_MEMORY_STORES_SOURCE_KEY = 'managed-memory-store-list'

export function managedMemoryStoreListQueryPrefix(scopeKey: string) {
  return [MANAGED_MEMORY_STORES_QUERY_ROOT, scopeKey, MANAGED_MEMORY_STORES_SOURCE_KEY] as const
}

export function managedMemoryStoreOptionsQueryKey(scopeKey: string) {
  return [MANAGED_MEMORY_STORES_QUERY_ROOT, scopeKey, 'options', false] as const
}

export function managedMemoryDirectoryQueryKey(scopeKey: string, storeId: MemoryStoreId | null) {
  return [MANAGED_MEMORY_STORES_QUERY_ROOT, scopeKey, storeId, 'memories', 'full'] as const
}

export async function fetchManagedMemoryStores(
  request: ManagedMemoryStorePageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<MemoryStore, MemoryStoreId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('memory_stores', {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseMemoryStoreResponse,
    parseCursor: parseMemoryStoreId,
    responseName: 'Memory Store list response',
  })
}

export async function fetchManagedMemoryStoreOptions(
  requestScope: ManagedRequestScope,
): Promise<MemoryStore[]> {
  const memoryStores = await collectManagedCursorPages<MemoryStore, MemoryStoreId>({
    responseName: 'Memory Store options pagination',
    fetchPage: (afterId) =>
      fetchManagedMemoryStores(
        {
          limit: MEMORY_STORE_OPTION_PAGE_SIZE,
          afterId,
          includeArchived: false,
        },
        requestScope,
      ),
  })
  return memoryStores.filter((memoryStore) => !memoryStore.archived_at)
}

export async function fetchManagedMemories(
  storeId: MemoryStoreId,
  request: ManagedMemoryPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<MemoryRecord, MemoryId>> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('memory_stores', storeId, ['memories'], {
      limit: request.limit,
      after_id: request.afterId,
      view: request.view,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseMemoryResponse,
    parseCursor: parseMemoryId,
    responseName: 'Memory directory response',
  })
}

export function fetchManagedMemoryDirectory(
  storeId: MemoryStoreId,
  requestScope: ManagedRequestScope,
): Promise<MemoryRecord[]> {
  return collectManagedCursorPages<MemoryRecord, MemoryId>({
    responseName: 'Memory directory pagination',
    fetchPage: (afterId) =>
      fetchManagedMemories(
        storeId,
        { limit: MEMORY_DIRECTORY_PAGE_SIZE, afterId, view: 'full' },
        requestScope,
      ),
  })
}

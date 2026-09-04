'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedMemoryStores,
  MANAGED_MEMORY_STORES_QUERY_ROOT,
  MANAGED_MEMORY_STORES_SOURCE_KEY,
} from '@/lib/managed/memory-store-client'
import { parseMemoryStoreId, type MemoryStoreId } from '@/types/entity-id'
import type { MemoryStore } from '@/types/managed'

export function useManagedMemoryStoreList(includeArchived: boolean) {
  return usePaginatedList<MemoryStore, MemoryStoreId>({
    queryKey: MANAGED_MEMORY_STORES_QUERY_ROOT,
    sourceKey: MANAGED_MEMORY_STORES_SOURCE_KEY,
    includeArchived,
    parseCursor: parseMemoryStoreId,
    fetchPage: fetchManagedMemoryStores,
  })
}

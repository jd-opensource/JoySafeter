'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedFiles,
  MANAGED_FILES_QUERY_ROOT,
  MANAGED_FILES_SOURCE_KEY,
} from '@/lib/managed/file-client'
import { parseFileId, type FileId } from '@/types/entity-id'
import type { FileRecord } from '@/types/managed'

export function useManagedFileList() {
  return usePaginatedList<FileRecord, FileId>({
    queryKey: MANAGED_FILES_QUERY_ROOT,
    sourceKey: MANAGED_FILES_SOURCE_KEY,
    parseCursor: parseFileId,
    fetchPage: fetchManagedFiles,
  })
}

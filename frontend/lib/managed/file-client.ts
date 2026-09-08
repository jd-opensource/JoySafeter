import { managedGet } from '@/lib/api-client'
import { apiCollectionPath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseFileId, type FileId, type SessionId } from '@/types/entity-id'
import type { FileRecord } from '@/types/managed'

import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'
import { parseFileResponse } from './file-response-parsers'

const FILE_OPTION_PAGE_SIZE = 100

export interface ManagedFilePageRequest {
  limit?: number
  afterId?: FileId
  sessionId?: SessionId
}

export const MANAGED_FILES_QUERY_ROOT = 'files'
export const MANAGED_FILES_SOURCE_KEY = 'managed-file-list'

export function managedFileListQueryPrefix(scopeKey: string) {
  return [MANAGED_FILES_QUERY_ROOT, scopeKey, MANAGED_FILES_SOURCE_KEY] as const
}

export function managedFileOptionsQueryKey(scopeKey: string) {
  return [MANAGED_FILES_QUERY_ROOT, scopeKey, 'options'] as const
}

export async function fetchManagedFiles(
  request: ManagedFilePageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<FileRecord, FileId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('files', {
      limit: request.limit,
      after_id: request.afterId,
      scope_id: request.sessionId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseFileResponse,
    parseCursor: parseFileId,
    responseName: 'File list response',
  })
}

export async function fetchManagedFileOptions(
  requestScope: ManagedRequestScope,
): Promise<FileRecord[]> {
  return collectManagedCursorPages<FileRecord, FileId>({
    responseName: 'File options pagination',
    fetchPage: (afterId) =>
      fetchManagedFiles(
        {
          limit: FILE_OPTION_PAGE_SIZE,
          afterId,
        },
        requestScope,
      ),
  })
}

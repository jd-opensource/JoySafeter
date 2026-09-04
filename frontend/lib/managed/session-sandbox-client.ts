import { managedFetchResponse, managedGet } from '@/lib/api-client'
import { apiResourceSubpath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import type { SessionId } from '@/types/entity-id'

export interface ManagedSessionSandboxFileEntry {
  name: string
  path: string
  type: 'file' | 'directory' | string
  size: number
  mtime: number
}

export interface ManagedSessionSandboxFileList {
  path: string
  entries: ManagedSessionSandboxFileEntry[]
}

export interface ManagedSessionSandboxFileContent {
  path: string
  encoding?: string
  content?: string
  content_base64?: string
  content_type?: string
  filename?: string
}

export function managedSessionSandboxFilesQueryKey(
  scopeKey: string,
  sessionId: SessionId,
  path: string,
) {
  return ['session-sandbox-files', scopeKey, sessionId, path] as const
}

export function managedSessionSandboxFileContentQueryKey(
  scopeKey: string,
  sessionId: SessionId,
  path: string | null,
) {
  return ['session-sandbox-file-content', scopeKey, sessionId, path] as const
}

function parseSandboxFileEntry(response: unknown): ManagedSessionSandboxFileEntry {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Invalid sandbox file entry')
  }
  const raw = response as Record<string, unknown>
  if (
    typeof raw.name !== 'string' ||
    typeof raw.path !== 'string' ||
    typeof raw.type !== 'string' ||
    typeof raw.size !== 'number' ||
    typeof raw.mtime !== 'number'
  ) {
    throw new Error('Invalid sandbox file entry')
  }
  return {
    name: raw.name,
    path: raw.path,
    type: raw.type,
    size: raw.size,
    mtime: raw.mtime,
  }
}

function parseSandboxFileContent(response: unknown): ManagedSessionSandboxFileContent {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Invalid sandbox file content response')
  }
  const raw = response as Record<string, unknown>
  if (typeof raw.path !== 'string') {
    throw new Error('Invalid sandbox file content response')
  }
  for (const field of [
    'encoding',
    'content',
    'content_base64',
    'content_type',
    'filename',
  ] as const) {
    if (raw[field] !== undefined && typeof raw[field] !== 'string') {
      throw new Error('Invalid sandbox file content response')
    }
  }
  return {
    path: raw.path,
    ...(raw.encoding !== undefined ? { encoding: raw.encoding as string } : {}),
    ...(raw.content !== undefined ? { content: raw.content as string } : {}),
    ...(raw.content_base64 !== undefined ? { content_base64: raw.content_base64 as string } : {}),
    ...(raw.content_type !== undefined ? { content_type: raw.content_type as string } : {}),
    ...(raw.filename !== undefined ? { filename: raw.filename as string } : {}),
  }
}

export async function fetchManagedSessionSandboxFiles(
  sessionId: SessionId,
  path: string,
  requestScope: ManagedRequestScope,
): Promise<ManagedSessionSandboxFileList> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('sessions', sessionId, ['sandbox', 'files'], { path }),
    {
      ...managedRequestOptions(requestScope),
      timeout: 20000,
    },
  )
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Invalid sandbox file list response')
  }
  const raw = response as { path?: unknown; entries?: unknown }
  if (typeof raw.path !== 'string' || !Array.isArray(raw.entries)) {
    throw new Error('Invalid sandbox file list response')
  }
  return {
    path: raw.path,
    entries: raw.entries.map(parseSandboxFileEntry),
  }
}

export async function fetchManagedSessionSandboxFileContent(
  sessionId: SessionId,
  path: string,
  requestScope: ManagedRequestScope,
): Promise<ManagedSessionSandboxFileContent> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('sessions', sessionId, ['sandbox', 'files', 'content'], { path }),
    {
      ...managedRequestOptions(requestScope),
      timeout: 20000,
    },
  )
  return parseSandboxFileContent(response)
}

export function fetchManagedSessionSandboxDownload(
  sessionId: SessionId,
  path: string,
  requestScope: ManagedRequestScope,
  options: { archive?: boolean } = {},
): Promise<Response> {
  return managedFetchResponse(
    apiResourceSubpath(
      'sessions',
      sessionId,
      ['sandbox', 'files', options.archive ? 'archive' : 'raw'],
      { path },
    ),
    managedRequestOptions(requestScope),
  )
}

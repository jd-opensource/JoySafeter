import {
  parseFileId,
  parseOptionalId,
  parseSessionId,
  parseSessionResourceId,
} from '@/types/entity-id'
import type {
  FileRecord,
  SessionFileResource,
  SessionRepoResource,
  SessionResource,
} from '@/types/managed'

type RawFileRecord = Omit<FileRecord, 'id' | 'session_id'> & {
  id: string
  session_id?: string | null
}

type RawSessionFileResource = Omit<SessionFileResource, 'id' | 'file_id'> & {
  id: string
  file_id: string
}

type RawSessionRepoResource = Omit<SessionRepoResource, 'id'> & { id: string }

export function parseFileResponse(response: unknown): FileRecord {
  const raw = response as RawFileRecord
  return {
    ...raw,
    id: parseFileId(raw.id),
    session_id: parseOptionalId(raw.session_id, parseSessionId),
  }
}

export function parseFileListResponse(response: unknown): FileRecord[] {
  return (response as RawFileRecord[]).map(parseFileResponse)
}

export function parseSessionFileResourceResponse(response: unknown): SessionFileResource {
  const raw = response as RawSessionFileResource
  return {
    ...raw,
    id: parseSessionResourceId(raw.id),
    file_id: parseFileId(raw.file_id),
  }
}

export function parseSessionRepoResourceResponse(response: unknown): SessionRepoResource {
  const raw = response as RawSessionRepoResource
  return { ...raw, id: parseSessionResourceId(raw.id) }
}

export function parseSessionResourceResponse(response: unknown): SessionResource {
  const raw = response as { type?: unknown }
  if (raw.type === 'file') return parseSessionFileResourceResponse(response)
  if (raw.type === 'github_repository') return parseSessionRepoResourceResponse(response)
  throw new TypeError(`Unsupported session resource type: ${String(raw.type)}`)
}

export function parseSessionResourceListResponse(response: unknown): SessionResource[] {
  return (response as unknown[]).map(parseSessionResourceResponse)
}

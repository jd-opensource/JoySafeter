import {
  parseMemoryId,
  parseMemoryStoreId,
  parseMemoryVersionId,
  type MemoryId,
  type MemoryStoreId,
  type MemoryVersionId,
} from '@/types/entity-id'
import type { MemoryStore } from '@/types/managed'

export interface MemoryRecord {
  id: MemoryId
  memory_store_id: MemoryStoreId
  path: string
  content: string
  content_size_bytes: number
  version?: number
  memory_version_id?: MemoryVersionId | null
  metadata: Record<string, string>
  created_at: string
  updated_at: string
}

type RawMemoryStore = Omit<MemoryStore, 'id'> & { id: string }
type RawMemoryRecord = Omit<MemoryRecord, 'id' | 'memory_store_id' | 'memory_version_id'> & {
  id: string
  memory_store_id: string
  memory_version_id?: string | null
}

export function parseMemoryStoreResponse(response: unknown): MemoryStore {
  const raw = response as RawMemoryStore
  return { ...raw, id: parseMemoryStoreId(raw.id) }
}

export function parseMemoryResponse(response: unknown): MemoryRecord {
  const raw = response as RawMemoryRecord
  return {
    ...raw,
    id: parseMemoryId(raw.id),
    memory_store_id: parseMemoryStoreId(raw.memory_store_id),
    memory_version_id:
      raw.memory_version_id == null
        ? raw.memory_version_id
        : parseMemoryVersionId(raw.memory_version_id),
  }
}

export function parseMemoryListResponse(response: unknown): MemoryRecord[] {
  const raw = response as unknown[] | { data?: unknown[] }
  const data = Array.isArray(raw) ? raw : raw.data || []
  return data.map(parseMemoryResponse)
}

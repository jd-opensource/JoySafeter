import { describe, expect, it } from 'vitest'

import {
  parseMemoryListResponse,
  parseMemoryResponse,
  parseMemoryStoreResponse,
} from './memory-response-parsers'

const STORE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'
const MEMORY_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f041'
const VERSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f042'

const rawMemory = () => ({
  id: `mem_${MEMORY_UUID}`,
  memory_store_id: `memstore_${STORE_UUID}`,
  memory_version_id: `memver_${VERSION_UUID}`,
  path: '/notes.txt',
  content: 'hello',
  content_size_bytes: 5,
  metadata: {},
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('memory response parsers', () => {
  it('brands store, memory, and version IDs', () => {
    expect(parseMemoryStoreResponse({ ...rawMemory(), id: `memstore_${STORE_UUID}` }).id).toBe(
      `memstore_${STORE_UUID}`,
    )
    expect(parseMemoryResponse(rawMemory()).memory_version_id).toBe(`memver_${VERSION_UUID}`)
    expect(parseMemoryListResponse({ data: [rawMemory()] })[0].id).toBe(`mem_${MEMORY_UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseMemoryResponse({ ...rawMemory(), id: MEMORY_UUID })).toThrow()
    expect(() =>
      parseMemoryResponse({ ...rawMemory(), memory_store_id: `mem_${STORE_UUID}` }),
    ).toThrow()
  })
})

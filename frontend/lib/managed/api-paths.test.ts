import { describe, expect, it } from 'vitest'

import { apiCollectionPath, apiResourceId, apiResourcePath, apiResourceSubpath } from './api-paths'

describe('managed API path helpers', () => {
  it('normalizes prefixed UI ids before building API paths', () => {
    expect(apiResourceId('sched_task_123')).toBe('123')
    expect(apiResourceId('memstore_abc')).toBe('abc')
    expect(apiResourceId('sklfile_def')).toBe('def')
    expect(apiResourcePath('memory_stores', 'memstore_abc', 'archive')).toBe(
      '/memory_stores/abc/archive',
    )
  })

  it('builds collection and child paths with encoded segments and query params', () => {
    expect(apiCollectionPath('/sessions/', { limit: 50, include_archived: false })).toBe(
      '/sessions?limit=50&include_archived=false',
    )
    expect(apiCollectionPath('/files?scope_id=sess_1', { limit: 20 })).toBe(
      '/files?scope_id=sess_1&limit=20',
    )
    expect(
      apiResourceSubpath('vaults', 'vault_v1', ['credentials', 'cred/a'], { limit: 100 }),
    ).toBe('/vaults/v1/credentials/cred%2Fa?limit=100')
  })
})

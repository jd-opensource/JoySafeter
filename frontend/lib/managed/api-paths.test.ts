import { describe, expect, it } from 'vitest'

import { apiCollectionPath, apiResourceId, apiResourcePath, apiResourceSubpath } from './api-paths'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'

describe('managed API path helpers', () => {
  it('preserves canonical typed ids at the public API boundary', () => {
    expect(apiResourceId(`agent_${UUID}`)).toBe(`agent_${UUID}`)
    expect(apiResourceId(`sess_${UUID}`)).toBe(`sess_${UUID}`)
    expect(apiResourceId(`task_${UUID}`)).toBe(`task_${UUID}`)
    expect(apiResourceId(`trig_${UUID}`)).toBe(`trig_${UUID}`)
    expect(apiResourceId(`env_${UUID}`)).toBe(`env_${UUID}`)
    expect(apiResourceId(`secret_${UUID}`)).toBe(`secret_${UUID}`)
    expect(apiResourceId(`vault_${UUID}`)).toBe(`vault_${UUID}`)
    expect(apiResourceId(`cred_${UUID}`)).toBe(`cred_${UUID}`)
    expect(apiResourceId(`skill_${UUID}`)).toBe(`skill_${UUID}`)
    expect(apiResourceId(`sklfile_${UUID}`)).toBe(`sklfile_${UUID}`)
    expect(apiResourceId(`sklscan_${UUID}`)).toBe(`sklscan_${UUID}`)
    expect(apiResourceId(`sklver_${UUID}`)).toBe(`sklver_${UUID}`)
    expect(apiResourceId(`sklvfile_${UUID}`)).toBe(`sklvfile_${UUID}`)
    expect(apiResourceId(`skluse_${UUID}`)).toBe(`skluse_${UUID}`)
    expect(apiResourceId(`file_${UUID}`)).toBe(`file_${UUID}`)
    expect(apiResourceId(`sesrsc_${UUID}`)).toBe(`sesrsc_${UUID}`)
    expect(apiResourcePath('agents', `agent_${UUID}`, 'archive')).toBe(
      `/agents/agent_${UUID}/archive`,
    )
  })

  it('rejects bare and malformed resource ids', () => {
    expect(() => apiResourceId(UUID)).toThrow(TypeError)
    expect(() => apiResourceId(`task_agent_${UUID}`)).toThrow(TypeError)
  })

  it('preserves canonical memory resource IDs', () => {
    const storeId = 'memstore_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'
    expect(apiResourceId(storeId)).toBe(storeId)
    expect(apiResourcePath('memory_stores', storeId, 'archive')).toBe(
      `/memory_stores/${storeId}/archive`,
    )
  })

  it('builds collection and child paths with encoded segments and query params', () => {
    expect(apiCollectionPath('/sessions/', { limit: 50, include_archived: false })).toBe(
      '/sessions?limit=50&include_archived=false',
    )
    expect(apiCollectionPath(`/files?scope_id=sess_${UUID}`, { limit: 20 })).toBe(
      `/files?scope_id=sess_${UUID}&limit=20`,
    )
    expect(
      apiResourceSubpath('vaults', `vault_${UUID}`, ['credentials', `cred_${UUID}`], {
        limit: 100,
      }),
    ).toBe(`/vaults/vault_${UUID}/credentials/cred_${UUID}?limit=100`)
    expect(apiCollectionPath('skills/usage/search', { limit: 5, target_hash: 'sha256:abc' })).toBe(
      '/skills/usage/search?limit=5&target_hash=sha256%3Aabc',
    )
  })
})

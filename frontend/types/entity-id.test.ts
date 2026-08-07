import { describe, expect, it } from 'vitest'

import { entityIdUuid, shortEntityId } from '@/lib/managed/id'

import {
  ENTITY_ID_PREFIXES,
  isEntityId,
  parseAnyEntityId,
  parseAgentId,
  parseEnvironmentId,
  parseEventId,
  parseSecretId,
  parseSessionId,
  parseTaskId,
  parseVaultId,
  parseCredentialId,
  parseSandboxId,
  parseMemoryStoreId,
  parseMemoryId,
  parseMemoryVersionId,
  parseSkillFileId,
  parseSkillId,
  parseSkillSecurityScanId,
  parseSkillUsageId,
  parseSkillVersionFileId,
  parseSkillVersionId,
  parseFileId,
  parseSessionResourceId,
  parseStorageGrantId,
  parseStorageMountAuditId,
  parseStorageVolumeId,
} from './entity-id'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'

describe('typed entity ids', () => {
  it('accepts canonical prefixed UUIDs', () => {
    expect(parseAgentId(`agent_${UUID}`)).toBe(`agent_${UUID}`)
    expect(parseSessionId(`sess_${UUID}`)).toBe(`sess_${UUID}`)
    expect(parseTaskId(`task_${UUID}`)).toBe(`task_${UUID}`)
    expect(parseEnvironmentId(`env_${UUID}`)).toBe(`env_${UUID}`)
    expect(parseSecretId(`secret_${UUID}`)).toBe(`secret_${UUID}`)
    expect(parseVaultId(`vault_${UUID}`)).toBe(`vault_${UUID}`)
    expect(parseCredentialId(`cred_${UUID}`)).toBe(`cred_${UUID}`)
    expect(parseSandboxId(`sbx_${UUID}`)).toBe(`sbx_${UUID}`)
    expect(parseMemoryStoreId(`memstore_${UUID}`)).toBe(`memstore_${UUID}`)
    expect(parseMemoryId(`mem_${UUID}`)).toBe(`mem_${UUID}`)
    expect(parseMemoryVersionId(`memver_${UUID}`)).toBe(`memver_${UUID}`)
    expect(parseSkillId(`skill_${UUID}`)).toBe(`skill_${UUID}`)
    expect(parseSkillFileId(`sklfile_${UUID}`)).toBe(`sklfile_${UUID}`)
    expect(parseSkillSecurityScanId(`sklscan_${UUID}`)).toBe(`sklscan_${UUID}`)
    expect(parseSkillVersionId(`sklver_${UUID}`)).toBe(`sklver_${UUID}`)
    expect(parseSkillVersionFileId(`sklvfile_${UUID}`)).toBe(`sklvfile_${UUID}`)
    expect(parseSkillUsageId(`skluse_${UUID}`)).toBe(`skluse_${UUID}`)
    expect(parseFileId(`file_${UUID}`)).toBe(`file_${UUID}`)
    expect(parseSessionResourceId(`sesrsc_${UUID}`)).toBe(`sesrsc_${UUID}`)
    expect(parseEventId(`evt_${UUID}`)).toBe(`evt_${UUID}`)
  })

  it('rejects bare UUIDs and cross-entity prefixes', () => {
    expect(() => parseAgentId(UUID)).toThrow(TypeError)
    expect(() => parseAgentId(`sess_${UUID}`)).toThrow(TypeError)
    expect(() => parseSessionId(`task_${UUID}`)).toThrow(TypeError)
    expect(() => parseEnvironmentId(`agent_${UUID}`)).toThrow(TypeError)
    expect(() => parseSecretId(UUID)).toThrow(TypeError)
    expect(() => parseSecretId(`env_${UUID}`)).toThrow(TypeError)
    expect(() => parseVaultId(UUID)).toThrow(TypeError)
    expect(() => parseCredentialId(`vault_${UUID}`)).toThrow(TypeError)
    expect(() => parseSandboxId(UUID)).toThrow(TypeError)
    expect(() => parseSandboxId(`task_${UUID}`)).toThrow(TypeError)
    expect(() => parseMemoryStoreId(UUID)).toThrow(TypeError)
    expect(() => parseMemoryId(`memver_${UUID}`)).toThrow(TypeError)
    expect(() => parseSkillId(UUID)).toThrow(TypeError)
    expect(() => parseSkillFileId(`skill_${UUID}`)).toThrow(TypeError)
    expect(() => parseFileId(UUID)).toThrow(TypeError)
    expect(() => parseSessionResourceId(`file_${UUID}`)).toThrow(TypeError)
    expect(() => parseEventId(UUID)).toThrow(TypeError)
  })

  it('rejects prefixed non-UUID fixtures', () => {
    expect(isEntityId('agent_123', 'agent')).toBe(false)
    expect(() => parseTaskId('task_test')).toThrow(TypeError)
  })

  it('parses every registered canonical entity id', () => {
    for (const prefix of Object.values(ENTITY_ID_PREFIXES)) {
      expect(parseAnyEntityId(`${prefix}${UUID}`)).toBe(`${prefix}${UUID}`)
    }
  })

  it('registers every storage resource identity prefix', () => {
    expect(ENTITY_ID_PREFIXES).toMatchObject({
      storageVolume: 'vol_',
      storageGrant: 'stgrant_',
      storageMountAudit: 'staudit_',
    })
    expect(parseAnyEntityId(`vol_${UUID}`)).toBe(`vol_${UUID}`)
    expect(parseAnyEntityId(`stgrant_${UUID}`)).toBe(`stgrant_${UUID}`)
    expect(parseAnyEntityId(`staudit_${UUID}`)).toBe(`staudit_${UUID}`)
    expect(parseStorageVolumeId(`vol_${UUID}`)).toBe(`vol_${UUID}`)
    expect(parseStorageGrantId(`stgrant_${UUID}`)).toBe(`stgrant_${UUID}`)
    expect(parseStorageMountAuditId(`staudit_${UUID}`)).toBe(`staudit_${UUID}`)
    expect(() => parseStorageVolumeId(UUID)).toThrow(TypeError)
    expect(() => parseStorageGrantId(`vol_${UUID}`)).toThrow(TypeError)
    expect(() => parseStorageMountAuditId(`stgrant_${UUID}`)).toThrow(TypeError)
  })

  it('rejects bare and stacked entity ids', () => {
    expect(() => parseAnyEntityId(UUID)).toThrow(TypeError)
    expect(() => parseAnyEntityId(`agent_sess_${UUID}`)).toThrow(TypeError)
  })

  it('formats validated entity ids for display only', () => {
    const agentId = parseAgentId(`agent_${UUID}`)

    expect(entityIdUuid(agentId, 'agent')).toBe(UUID)
    expect(shortEntityId(agentId, 'agent', 6)).toBe('agent_018f6f')
  })
})

const UUID_PATTERN = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

const entityIdBrand: unique symbol = Symbol('entityIdBrand')

export const ENTITY_ID_PREFIXES = {
  agent: 'agent_',
  session: 'sess_',
  task: 'task_',
  trigger: 'trig_',
  environment: 'env_',
  secret: 'secret_',
  vault: 'vault_',
  credential: 'cred_',
  sandbox: 'sbx_',
  memoryStore: 'memstore_',
  memory: 'mem_',
  memoryVersion: 'memver_',
  skill: 'skill_',
  skillFile: 'sklfile_',
  skillSecurityScan: 'sklscan_',
  skillVersion: 'sklver_',
  skillVersionFile: 'sklvfile_',
  skillUsage: 'skluse_',
  file: 'file_',
  sessionResource: 'sesrsc_',
  event: 'evt_',
  storageVolume: 'vol_',
  storageGrant: 'stgrant_',
  storageMountAudit: 'staudit_',
} as const

export type EntityKind = keyof typeof ENTITY_ID_PREFIXES
export type EntityIdPrefix = (typeof ENTITY_ID_PREFIXES)[EntityKind]

export type EntityId<Prefix extends EntityIdPrefix> = `${Prefix}${string}` & {
  readonly [entityIdBrand]: Prefix
}

export type AgentId = EntityId<'agent_'>
export type SessionId = EntityId<'sess_'>
export type TaskId = EntityId<'task_'>
export type TriggerId = EntityId<'trig_'>
export type EnvironmentId = EntityId<'env_'>
export type SecretId = EntityId<'secret_'>
export type VaultId = EntityId<'vault_'>
export type CredentialId = EntityId<'cred_'>
export type SandboxId = EntityId<'sbx_'>
export type MemoryStoreId = EntityId<'memstore_'>
export type MemoryId = EntityId<'mem_'>
export type MemoryVersionId = EntityId<'memver_'>
export type SkillId = EntityId<'skill_'>
export type SkillFileId = EntityId<'sklfile_'>
export type SkillSecurityScanId = EntityId<'sklscan_'>
export type SkillVersionId = EntityId<'sklver_'>
export type SkillVersionFileId = EntityId<'sklvfile_'>
export type SkillUsageId = EntityId<'skluse_'>
export type FileId = EntityId<'file_'>
export type SessionResourceId = EntityId<'sesrsc_'>
export type EventId = EntityId<'evt_'>
export type StorageVolumeId = EntityId<'vol_'>
export type StorageGrantId = EntityId<'stgrant_'>
export type StorageMountAuditId = EntityId<'staudit_'>
export type AnyEntityId = {
  [Kind in EntityKind]: EntityId<(typeof ENTITY_ID_PREFIXES)[Kind]>
}[EntityKind]

const ENTITY_ID_PATTERNS: Record<EntityKind, RegExp> = Object.fromEntries(
  Object.entries(ENTITY_ID_PREFIXES).map(([kind, prefix]) => [
    kind,
    new RegExp(`^${prefix}${UUID_PATTERN}$`, 'i'),
  ]),
) as Record<EntityKind, RegExp>

export function isEntityId<Kind extends EntityKind>(
  value: string,
  kind: Kind,
): value is EntityId<(typeof ENTITY_ID_PREFIXES)[Kind]> {
  return ENTITY_ID_PATTERNS[kind].test(value)
}

export function parseEntityId<Kind extends EntityKind>(
  value: string,
  kind: Kind,
): EntityId<(typeof ENTITY_ID_PREFIXES)[Kind]> {
  if (!isEntityId(value, kind)) {
    throw new TypeError(`Expected ${ENTITY_ID_PREFIXES[kind]}<uuid>, received ${value}`)
  }
  return value
}

export function parseAnyEntityId(value: string): AnyEntityId {
  for (const kind of Object.keys(ENTITY_ID_PREFIXES) as EntityKind[]) {
    if (isEntityId(value, kind)) return value as AnyEntityId
  }
  throw new TypeError(`Expected a registered entity ID, received ${value}`)
}

export function parseAgentId(value: string): AgentId {
  return parseEntityId(value, 'agent')
}

export function tryParseAgentId(value: string | null | undefined): AgentId | null {
  return value && isEntityId(value, 'agent') ? value : null
}

export function parseSessionId(value: string): SessionId {
  return parseEntityId(value, 'session')
}

export function parseTaskId(value: string): TaskId {
  return parseEntityId(value, 'task')
}

export function parseTriggerId(value: string): TriggerId {
  return parseEntityId(value, 'trigger')
}

export function parseEnvironmentId(value: string): EnvironmentId {
  return parseEntityId(value, 'environment')
}

export function tryParseEnvironmentId(value: string | null | undefined): EnvironmentId | null {
  return value && isEntityId(value, 'environment') ? value : null
}

export function parseSecretId(value: string): SecretId {
  return parseEntityId(value, 'secret')
}

export function parseVaultId(value: string): VaultId {
  return parseEntityId(value, 'vault')
}

export function tryParseVaultId(value: string | null | undefined): VaultId | null {
  return value && isEntityId(value, 'vault') ? value : null
}

export function parseCredentialId(value: string): CredentialId {
  return parseEntityId(value, 'credential')
}

export function parseSandboxId(value: string): SandboxId {
  return parseEntityId(value, 'sandbox')
}

export function parseMemoryStoreId(value: string): MemoryStoreId {
  return parseEntityId(value, 'memoryStore')
}

export function parseMemoryId(value: string): MemoryId {
  return parseEntityId(value, 'memory')
}

export function parseMemoryVersionId(value: string): MemoryVersionId {
  return parseEntityId(value, 'memoryVersion')
}

export function parseSkillId(value: string): SkillId {
  return parseEntityId(value, 'skill')
}

export function tryParseSkillId(value: string | null | undefined): SkillId | null {
  return value && isEntityId(value, 'skill') ? value : null
}

export function parseSkillFileId(value: string): SkillFileId {
  return parseEntityId(value, 'skillFile')
}

export function parseSkillSecurityScanId(value: string): SkillSecurityScanId {
  return parseEntityId(value, 'skillSecurityScan')
}

export function parseSkillVersionId(value: string): SkillVersionId {
  return parseEntityId(value, 'skillVersion')
}

export function parseSkillVersionFileId(value: string): SkillVersionFileId {
  return parseEntityId(value, 'skillVersionFile')
}

export function parseSkillUsageId(value: string): SkillUsageId {
  return parseEntityId(value, 'skillUsage')
}

export function parseFileId(value: string): FileId {
  return parseEntityId(value, 'file')
}

export function parseSessionResourceId(value: string): SessionResourceId {
  return parseEntityId(value, 'sessionResource')
}

export function parseEventId(value: string): EventId {
  return parseEntityId(value, 'event')
}

export function parseStorageVolumeId(value: string): StorageVolumeId {
  return parseEntityId(value, 'storageVolume')
}

export function parseStorageGrantId(value: string): StorageGrantId {
  return parseEntityId(value, 'storageGrant')
}

export function parseStorageMountAuditId(value: string): StorageMountAuditId {
  return parseEntityId(value, 'storageMountAudit')
}

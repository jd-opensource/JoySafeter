import {
  parseEnvironmentId,
  parseSessionId,
  parseSessionResourceId,
  parseStorageGrantId,
  parseStorageMountAuditId,
  parseStorageVolumeId,
  type EnvironmentId,
  type SessionId,
  type StorageVolumeId,
} from '@/types/entity-id'
import type {
  SessionStorageMount,
  StorageMountAudit,
  StorageOrganizationGrant,
  StorageProjectGrant,
  StorageVolume,
} from '@/types/managed'

type RawStorageProjectGrant = Omit<StorageProjectGrant, 'id' | 'volume_id'> & {
  id: string
  volume_id: string
}

type RawStorageOrganizationGrant = Omit<StorageOrganizationGrant, 'id' | 'volume_id'> & {
  id: string
  volume_id: string
}

type RawStorageVolume = Omit<StorageVolume, 'id' | 'grants' | 'organization_grants'> & {
  id: string
  grants?: RawStorageProjectGrant[]
  organization_grants?: RawStorageOrganizationGrant[]
}

type RawSessionStorageMount = Omit<SessionStorageMount, 'id' | 'volume_id'> & {
  id: string
  volume_id: string
}

type RawStorageMountAudit = Omit<
  StorageMountAudit,
  'id' | 'volume_id' | 'session_id' | 'environment_id'
> & {
  id: string
  volume_id?: string | null
  session_id?: string | null
  environment_id?: string | null
}

function parseOptionalId<T>(
  value: string | null | undefined,
  parse: (raw: string) => T,
): T | null | undefined {
  return value == null ? value : parse(value)
}

export function parseStorageProjectGrantResponse(response: unknown): StorageProjectGrant {
  const raw = response as RawStorageProjectGrant
  return {
    ...raw,
    id: parseStorageGrantId(raw.id),
    volume_id: parseStorageVolumeId(raw.volume_id),
  }
}

export function parseStorageOrganizationGrantResponse(response: unknown): StorageOrganizationGrant {
  const raw = response as RawStorageOrganizationGrant
  return {
    ...raw,
    id: parseStorageGrantId(raw.id),
    volume_id: parseStorageVolumeId(raw.volume_id),
  }
}

export function parseStorageVolumeResponse(response: unknown): StorageVolume {
  const raw = response as RawStorageVolume
  return {
    ...raw,
    id: parseStorageVolumeId(raw.id),
    grants: raw.grants?.map(parseStorageProjectGrantResponse),
    organization_grants: raw.organization_grants?.map(parseStorageOrganizationGrantResponse),
  }
}

export function parseStorageVolumeListResponse(
  response: unknown,
): StorageVolume[] | { data?: StorageVolume[] | null } {
  if (Array.isArray(response)) return response.map(parseStorageVolumeResponse)
  const raw = response as { data?: unknown[] | null }
  return {
    ...raw,
    data: raw.data?.map(parseStorageVolumeResponse),
  }
}

export function parseSessionStorageMountResponse(response: unknown): SessionStorageMount {
  const raw = response as RawSessionStorageMount
  return {
    ...raw,
    id: parseSessionResourceId(raw.id),
    volume_id: parseStorageVolumeId(raw.volume_id),
  }
}

export function parseStorageMountAuditResponse(response: unknown): StorageMountAudit {
  const raw = response as RawStorageMountAudit
  return {
    ...raw,
    id: parseStorageMountAuditId(raw.id),
    volume_id: parseOptionalId<StorageVolumeId>(raw.volume_id, parseStorageVolumeId),
    session_id: parseOptionalId<SessionId>(raw.session_id, parseSessionId),
    environment_id: parseOptionalId<EnvironmentId>(raw.environment_id, parseEnvironmentId),
  }
}

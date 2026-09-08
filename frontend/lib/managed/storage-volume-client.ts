import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath } from '@/lib/managed/api-paths'
import { parseManagedCursorPage, type ManagedCursorPage } from '@/lib/managed/cursor-page'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import {
  parseStorageMountAuditId,
  type OrganizationId,
  type ProjectId,
  type StorageMountAuditId,
  type StorageVolumeId,
} from '@/types/entity-id'
import type {
  StorageMountAudit,
  StorageOrganizationGrant,
  StorageProjectGrant,
  StorageVolume,
  StorageVolumeCatalogItem,
} from '@/types/managed'

import {
  parseStorageMountAuditResponse,
  parseStorageOrganizationGrantResponse,
  parseStorageProjectGrantResponse,
  parseStorageVolumeResponse,
} from './storage-mount-response-parsers'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export const MANAGED_STORAGE_MOUNT_CATALOG_QUERY_ROOT = 'storage-mount-catalog'
export const MANAGED_STORAGE_VOLUMES_QUERY_ROOT = 'storage-volumes'
export const MANAGED_STORAGE_VOLUME_AUDIT_QUERY_ROOT = 'storage-volumes-audit'
export const MANAGED_STORAGE_VOLUME_AUDIT_SOURCE_KEY = 'managed-storage-volume-audit-list'

export type ManagedStorageVolumeView = 'organization' | 'platform'

export interface ManagedStorageMountAuditPageRequest {
  limit: number
  afterId?: StorageMountAuditId
  volumeId?: StorageVolumeId | null
  search?: string
}

export interface ManagedStorageVolumeWrite {
  backend_type: string
  display_name: string
  description: string
  max_access: string
  allowed_prefixes: string[]
  docker: Record<string, unknown>
  k8s: Record<string, unknown>
  enabled: boolean
}

export interface ManagedStorageProjectGrantWrite {
  project_id: ProjectId
  max_access: string
  allowed_prefixes: string[]
  enabled: boolean
}

export interface ManagedStorageOrganizationGrantWrite {
  org_id: OrganizationId
  max_access: string
  allowed_prefixes: string[]
  enabled: boolean
}

export function managedStorageMountCatalogQueryKey(scopeKey: string) {
  return [MANAGED_STORAGE_MOUNT_CATALOG_QUERY_ROOT, scopeKey] as const
}

export function managedStorageVolumesQueryKey(scopeKey: string, view: ManagedStorageVolumeView) {
  return [MANAGED_STORAGE_VOLUMES_QUERY_ROOT, scopeKey, view] as const
}

export function managedStorageVolumeAuditQueryPrefix(scopeKey: string) {
  return [
    MANAGED_STORAGE_VOLUME_AUDIT_QUERY_ROOT,
    scopeKey,
    MANAGED_STORAGE_VOLUME_AUDIT_SOURCE_KEY,
  ] as const
}

function optionalString(raw: Record<string, unknown>, field: string): string | undefined {
  const value = raw[field]
  if (value === undefined) return undefined
  if (typeof value !== 'string') {
    throw new TypeError(`Expected storage catalog item.${field} to be a string`)
  }
  return value
}

function optionalBoolean(raw: Record<string, unknown>, field: string): boolean | undefined {
  const value = raw[field]
  if (value === undefined) return undefined
  if (typeof value !== 'boolean') {
    throw new TypeError(`Expected storage catalog item.${field} to be a boolean`)
  }
  return value
}

function optionalNumber(raw: Record<string, unknown>, field: string): number | null | undefined {
  const value = raw[field]
  if (value === undefined || value === null) return value
  if (typeof value !== 'number') {
    throw new TypeError(`Expected storage catalog item.${field} to be a number or null`)
  }
  return value
}

function requiredString(raw: Record<string, unknown>, field: string): string {
  const value = raw[field]
  if (typeof value !== 'string') {
    throw new TypeError(`Expected storage catalog item.${field} to be a string`)
  }
  return value
}

function parseStorageMountCatalogItem(response: unknown): StorageVolumeCatalogItem {
  if (!isRecord(response)) throw new TypeError('Expected storage catalog item to be an object')
  const allowedPrefixes = response.allowed_prefixes
  if (
    allowedPrefixes !== undefined &&
    (!Array.isArray(allowedPrefixes) || allowedPrefixes.some((value) => typeof value !== 'string'))
  ) {
    throw new TypeError('Expected storage catalog item.allowed_prefixes to be a string array')
  }
  return {
    volume_ref: requiredString(response, 'volume_ref'),
    backend_type: optionalString(response, 'backend_type'),
    display_name: requiredString(response, 'display_name'),
    description: optionalString(response, 'description'),
    max_access: requiredString(response, 'max_access'),
    allowed_prefixes: allowedPrefixes as string[] | undefined,
    quota_bytes: optionalNumber(response, 'quota_bytes'),
    used_bytes: optionalNumber(response, 'used_bytes') ?? undefined,
    supports_docker: optionalBoolean(response, 'supports_docker'),
    supports_k8s: optionalBoolean(response, 'supports_k8s'),
  }
}

export async function fetchManagedStorageMountCatalog(
  requestScope: ManagedRequestScope,
): Promise<StorageVolumeCatalogItem[]> {
  const response = await managedGet<unknown>(
    '/storage-volumes/catalog',
    managedRequestOptions(requestScope),
  )
  if (!isRecord(response) || !Array.isArray(response.data)) {
    throw new TypeError('Expected storage catalog response.data to be an array')
  }
  return response.data.map(parseStorageMountCatalogItem)
}

export async function fetchManagedStorageVolumes(
  view: ManagedStorageVolumeView,
  requestScope: ManagedRequestScope,
): Promise<StorageVolume[]> {
  const response = await managedGet<unknown>(
    apiCollectionPath('storage-volumes', {
      include_disabled: true,
      scope: view === 'organization' ? 'organization' : undefined,
    }),
    managedRequestOptions(requestScope),
  )
  if (!isRecord(response) || !Array.isArray(response.data)) {
    throw new TypeError('Expected storage volume list response.data to be an array')
  }
  return response.data.map(parseStorageVolumeResponse)
}

export async function fetchManagedStorageMountAudits(
  request: ManagedStorageMountAuditPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<StorageMountAudit, StorageMountAuditId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('storage-volumes/audit/logs', {
      limit: request.limit,
      after_id: request.afterId,
      volume_id: request.volumeId,
      q: request.search?.trim() || undefined,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseStorageMountAuditResponse,
    parseCursor: parseStorageMountAuditId,
    responseName: 'Storage volume audit list response',
  })
}

export function createManagedStorageVolume(
  payload: ManagedStorageVolumeWrite & { volume_ref: string },
  requestScope: ManagedRequestScope,
): Promise<StorageVolume> {
  return managedPost<unknown>(
    '/storage-volumes',
    payload,
    managedRequestOptions(requestScope),
  ).then(parseStorageVolumeResponse)
}

export function updateManagedStorageVolume(
  volumeId: StorageVolumeId,
  payload: Partial<ManagedStorageVolumeWrite>,
  requestScope: ManagedRequestScope,
): Promise<StorageVolume> {
  return managedPost<unknown>(
    apiResourcePath('storage-volumes', volumeId),
    payload,
    managedRequestOptions(requestScope),
  ).then(parseStorageVolumeResponse)
}

export function saveManagedStorageProjectGrant(
  volumeId: StorageVolumeId,
  payload: ManagedStorageProjectGrantWrite,
  requestScope: ManagedRequestScope,
): Promise<StorageProjectGrant> {
  return managedPost<unknown>(
    apiResourcePath('storage-volumes', volumeId, 'grants'),
    payload,
    managedRequestOptions(requestScope),
  ).then(parseStorageProjectGrantResponse)
}

export function saveManagedStorageOrganizationGrant(
  volumeId: StorageVolumeId,
  payload: ManagedStorageOrganizationGrantWrite,
  requestScope: ManagedRequestScope,
): Promise<StorageOrganizationGrant> {
  return managedPost<unknown>(
    apiResourcePath('storage-volumes', volumeId, 'organization-grants'),
    payload,
    managedRequestOptions(requestScope),
  ).then(parseStorageOrganizationGrantResponse)
}

export function deleteManagedStorageProjectGrant(
  volumeId: StorageVolumeId,
  projectId: ProjectId,
  requestScope: ManagedRequestScope,
) {
  return managedDelete(
    apiResourcePath('storage-volumes', volumeId, 'grants', projectId),
    managedRequestOptions(requestScope),
  )
}

export function deleteManagedStorageOrganizationGrant(
  volumeId: StorageVolumeId,
  organizationId: OrganizationId,
  requestScope: ManagedRequestScope,
) {
  return managedDelete(
    apiResourcePath('storage-volumes', volumeId, 'organization-grants', organizationId),
    managedRequestOptions(requestScope),
  )
}

export function deleteManagedStorageVolume(
  volumeId: StorageVolumeId,
  requestScope: ManagedRequestScope,
) {
  return managedDelete(
    apiResourcePath('storage-volumes', volumeId),
    managedRequestOptions(requestScope),
  )
}

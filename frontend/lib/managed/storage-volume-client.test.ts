import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID } from '@/test-utils/entity-ids'
import { parseStorageMountAuditId, parseStorageVolumeId } from '@/types/entity-id'

import {
  createManagedStorageVolume,
  deleteManagedStorageOrganizationGrant,
  deleteManagedStorageProjectGrant,
  deleteManagedStorageVolume,
  fetchManagedStorageMountAudits,
  fetchManagedStorageMountCatalog,
  fetchManagedStorageVolumes,
  managedStorageMountCatalogQueryKey,
  managedStorageVolumeAuditQueryPrefix,
  managedStorageVolumesQueryKey,
  saveManagedStorageOrganizationGrant,
  saveManagedStorageProjectGrant,
  updateManagedStorageVolume,
} from './storage-volume-client'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

const VOLUME_ID = parseStorageVolumeId('vol_018f6f42-0a51-7cc4-98c8-4f6f0ca5f124')
const AUDIT_ID = parseStorageMountAuditId('staudit_018f6f42-0a51-7cc4-98c8-4f6f0ca5f125')

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

describe('managed Storage mount catalog client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
    vi.mocked(managedPost).mockReset()
    vi.mocked(managedDelete).mockReset()
  })

  it('separates platform and organization volume caches and transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [
        {
          id: VOLUME_ID,
          volume_ref: 'datasets',
          display_name: 'Datasets',
          max_access: 'read_only',
          enabled: true,
        },
      ],
    })

    expect(managedStorageVolumesQueryKey(requestScope.key, 'platform')).not.toEqual(
      managedStorageVolumesQueryKey(requestScope.key, 'organization'),
    )
    await expect(fetchManagedStorageVolumes('organization', requestScope)).resolves.toEqual([
      expect.objectContaining({ id: VOLUME_ID, volume_ref: 'datasets' }),
    ])
    expect(managedGet).toHaveBeenCalledWith(
      '/storage-volumes?include_disabled=true&scope=organization',
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical storage volume list responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([])
    await expect(fetchManagedStorageVolumes('platform', requestScope)).rejects.toThrow(
      /storage volume list response\.data/,
    )
  })

  it('owns typed storage audit pagination and filter identity', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [
        {
          id: AUDIT_ID,
          volume_id: VOLUME_ID,
          action: 'mount',
          result: 'success',
          created_at: '2026-09-03T00:00:00Z',
        },
      ],
      has_more: false,
      first_id: AUDIT_ID,
      last_id: AUDIT_ID,
    })

    expect(managedStorageVolumeAuditQueryPrefix(requestScope.key)).toEqual([
      'storage-volumes-audit',
      requestScope.key,
      'managed-storage-volume-audit-list',
    ])
    await expect(
      fetchManagedStorageMountAudits(
        { limit: 25, afterId: AUDIT_ID, volumeId: VOLUME_ID, search: ' mount ' },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: AUDIT_ID, volume_id: VOLUME_ID })],
      hasMore: false,
      firstId: AUDIT_ID,
      lastId: AUDIT_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/storage-volumes/audit/logs?limit=25&after_id=${AUDIT_ID}&volume_id=${VOLUME_ID}&q=mount`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed storage audit pages', async () => {
    vi.mocked(managedGet).mockResolvedValue({ data: [], has_more: 'false' })
    await expect(fetchManagedStorageMountAudits({ limit: 25 }, requestScope)).rejects.toThrow(
      /Storage volume audit list response/,
    )
  })

  it('owns storage volume and grant lifecycle transport', async () => {
    const volumeResponse = {
      id: VOLUME_ID,
      volume_ref: 'datasets',
      display_name: 'Datasets',
      max_access: 'read_only',
      enabled: true,
    }
    vi.mocked(managedPost).mockResolvedValue(volumeResponse)
    vi.mocked(managedDelete).mockResolvedValue(undefined)
    const volumePayload = {
      backend_type: 'pvc',
      display_name: 'Datasets',
      description: '',
      max_access: 'read_only',
      allowed_prefixes: [],
      docker: {},
      k8s: { pvc: 'datasets' },
      enabled: true,
    }

    await createManagedStorageVolume({ ...volumePayload, volume_ref: 'datasets' }, requestScope)
    await updateManagedStorageVolume(VOLUME_ID, { enabled: false }, requestScope)

    vi.mocked(managedPost).mockResolvedValueOnce({
      id: 'stgrant_018f6f42-0a51-7cc4-98c8-4f6f0ca5f126',
      volume_id: VOLUME_ID,
      project_id: PROJECT_ID,
    })
    await saveManagedStorageProjectGrant(
      VOLUME_ID,
      { project_id: PROJECT_ID, max_access: 'read_only', allowed_prefixes: [], enabled: true },
      requestScope,
    )
    vi.mocked(managedPost).mockResolvedValueOnce({
      id: 'stgrant_018f6f42-0a51-7cc4-98c8-4f6f0ca5f127',
      volume_id: VOLUME_ID,
      org_id: ORGANIZATION_ID,
    })
    await saveManagedStorageOrganizationGrant(
      VOLUME_ID,
      { org_id: ORGANIZATION_ID, max_access: 'read_only', allowed_prefixes: [], enabled: true },
      requestScope,
    )
    await deleteManagedStorageProjectGrant(VOLUME_ID, PROJECT_ID, requestScope)
    await deleteManagedStorageOrganizationGrant(VOLUME_ID, ORGANIZATION_ID, requestScope)
    await deleteManagedStorageVolume(VOLUME_ID, requestScope)

    expect(managedPost).toHaveBeenNthCalledWith(
      1,
      '/storage-volumes',
      expect.objectContaining({ volume_ref: 'datasets' }),
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      2,
      `/storage-volumes/${VOLUME_ID}`,
      { enabled: false },
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedDelete).toHaveBeenNthCalledWith(
      1,
      `/storage-volumes/${VOLUME_ID}/grants/${PROJECT_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedDelete).toHaveBeenNthCalledWith(
      2,
      `/storage-volumes/${VOLUME_ID}/organization-grants/${ORGANIZATION_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedDelete).toHaveBeenNthCalledWith(
      3,
      `/storage-volumes/${VOLUME_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns the project-scoped query identity and strict transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [
        {
          volume_ref: 'storage-data',
          backend_type: 'pvc',
          display_name: 'Data',
          max_access: 'read_write',
          allowed_prefixes: ['datasets'],
          quota_bytes: null,
          supports_k8s: true,
        },
      ],
    })

    expect(managedStorageMountCatalogQueryKey(requestScope.key)).toEqual([
      'storage-mount-catalog',
      requestScope.key,
    ])
    await expect(fetchManagedStorageMountCatalog(requestScope)).resolves.toEqual([
      expect.objectContaining({ volume_ref: 'storage-data', display_name: 'Data' }),
    ])
    expect(managedGet).toHaveBeenCalledWith(
      '/storage-volumes/catalog',
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it.each([
    [{ data: null }],
    [{ data: [{ volume_ref: 'storage-data', display_name: 'Data' }] }],
    [
      {
        data: [
          {
            volume_ref: 'storage-data',
            display_name: 'Data',
            max_access: 'read_only',
            allowed_prefixes: [1],
          },
        ],
      },
    ],
  ])('rejects malformed catalog response %#', async (response) => {
    vi.mocked(managedGet).mockResolvedValue(response)
    await expect(fetchManagedStorageMountCatalog(requestScope)).rejects.toThrow()
  })
})

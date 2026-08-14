import { describe, expect, it } from 'vitest'

import {
  parseSessionStorageMountResponse,
  parseStorageMountAuditResponse,
  parseStorageOrganizationGrantResponse,
  parseStorageProjectGrantResponse,
  parseStorageVolumeListResponse,
  parseStorageVolumeResponse,
} from './storage-mount-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f012'

describe('storage mount response parsers', () => {
  it('parses every storage response identity', () => {
    const projectGrant = {
      id: `stgrant_${UUID}`,
      volume_id: `vol_${UUID}`,
      project_id: 'project-1',
    }
    const organizationGrant = {
      id: `stgrant_${UUID}`,
      volume_id: `vol_${UUID}`,
      org_id: 'org-1',
    }
    const volume = parseStorageVolumeResponse({
      id: `vol_${UUID}`,
      volume_ref: 'datasets',
      display_name: 'Datasets',
      max_access: 'read_only',
      enabled: true,
      grants: [projectGrant],
      organization_grants: [organizationGrant],
    })
    const list = parseStorageVolumeListResponse({ data: [volume] })
    const audit = parseStorageMountAuditResponse({
      id: `staudit_${UUID}`,
      volume_id: `vol_${UUID}`,
      session_id: `sess_${UUID}`,
      environment_id: `env_${UUID}`,
      action: 'mount',
      result: 'success',
      created_at: '2026-08-06T00:00:00Z',
    })
    const sessionMount = parseSessionStorageMountResponse({
      id: `sesrsc_${UUID}`,
      volume_id: `vol_${UUID}`,
      type: 'storage',
      name: 'datasets',
      volume_ref: 'datasets',
      mount_path: '/mnt/datasets',
      access: 'read_only',
      required: true,
      created_at: '2026-08-06T00:00:00Z',
    })

    expect(volume.id).toBe(`vol_${UUID}`)
    expect(volume.grants?.[0].id).toBe(`stgrant_${UUID}`)
    expect('data' in list ? list.data?.[0].id : undefined).toBe(`vol_${UUID}`)
    expect(parseStorageProjectGrantResponse(projectGrant).volume_id).toBe(`vol_${UUID}`)
    expect(parseStorageOrganizationGrantResponse(organizationGrant).id).toBe(`stgrant_${UUID}`)
    expect(audit.id).toBe(`staudit_${UUID}`)
    expect(audit.volume_id).toBe(`vol_${UUID}`)
    expect(audit.session_id).toBe(`sess_${UUID}`)
    expect(audit.environment_id).toBe(`env_${UUID}`)
    expect(sessionMount.id).toBe(`sesrsc_${UUID}`)
    expect(sessionMount.volume_id).toBe(`vol_${UUID}`)
  })

  it('rejects bare and cross-prefix storage identities', () => {
    expect(() =>
      parseStorageMountAuditResponse({
        id: `staudit_${UUID}`,
        volume_id: UUID,
        action: 'mount',
        result: 'success',
        created_at: '2026-08-06T00:00:00Z',
      }),
    ).toThrow()
    expect(() =>
      parseStorageMountAuditResponse({
        id: `vol_${UUID}`,
        volume_id: `staudit_${UUID}`,
        environment_id: `agent_${UUID}`,
        action: 'mount',
        result: 'success',
        created_at: '2026-08-06T00:00:00Z',
      }),
    ).toThrow()
    expect(() =>
      parseStorageVolumeResponse({
        id: UUID,
        volume_ref: 'datasets',
        display_name: 'Datasets',
        max_access: 'read_only',
        enabled: true,
      }),
    ).toThrow()
    expect(() =>
      parseStorageProjectGrantResponse({
        id: `vol_${UUID}`,
        volume_id: `vol_${UUID}`,
        project_id: 'project-1',
      }),
    ).toThrow()
    expect(() =>
      parseStorageOrganizationGrantResponse({
        id: `stgrant_${UUID}`,
        volume_id: `stgrant_${UUID}`,
        org_id: 'org-1',
      }),
    ).toThrow()
    expect(() =>
      parseSessionStorageMountResponse({
        id: `staudit_${UUID}`,
        volume_id: UUID,
        type: 'storage',
      }),
    ).toThrow()
  })
})

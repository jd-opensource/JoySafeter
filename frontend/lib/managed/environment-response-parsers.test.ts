import { describe, expect, it } from 'vitest'

import {
  parseEnvironmentListResponse,
  parseEnvironmentResponse,
} from './environment-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f010'

function rawEnvironment() {
  return {
    id: `env_${UUID}`,
    name: 'Environment',
    created_at: '2026-08-06T00:00:00Z',
    updated_at: '2026-08-06T00:00:00Z',
  }
}

describe('environment response parsers', () => {
  it('brands canonical environment ids at the API boundary', () => {
    const environment = parseEnvironmentResponse({
      ...rawEnvironment(),
      config: {
        storage_volumes: [
          {
            name: 'datasets',
            volume_id: `vol_${UUID}`,
            mount_path: '/mnt/datasets',
          },
        ],
      },
    })

    expect(environment.id).toBe(`env_${UUID}`)
    expect(environment.config?.storage_volumes?.[0].volume_id).toBe(`vol_${UUID}`)
    expect(parseEnvironmentListResponse([rawEnvironment()])[0].id).toBe(`env_${UUID}`)
  })

  it('rejects bare and cross-entity ids', () => {
    expect(() => parseEnvironmentResponse({ ...rawEnvironment(), id: UUID })).toThrow()
    expect(() => parseEnvironmentResponse({ ...rawEnvironment(), id: `agent_${UUID}` })).toThrow()
  })

  it.each([UUID, `staudit_${UUID}`])(
    'rejects invalid persisted environment storage volume id %s',
    (volumeId) => {
      expect(() =>
        parseEnvironmentResponse({
          ...rawEnvironment(),
          config: {
            storage_volumes: [{ volume_id: volumeId }],
          },
        }),
      ).toThrow(TypeError)
    },
  )
})

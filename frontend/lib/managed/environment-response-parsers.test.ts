import { describe, expect, it } from 'vitest'

import referenceContract from '../../../backend/contracts/credential_reference_contract.json'

import {
  CREDENTIAL_REFERENCE_KEYS,
  CREDENTIAL_REFERENCE_NORMALIZATION,
  CREDENTIAL_SNAPSHOT_SCHEMAS,
} from './credential-reference-contract'
import {
  CredentialReferenceCodec,
  parseEnvironmentListResponse,
  parseEnvironmentResponse,
} from './environment-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f010'
const referenceCodec = new CredentialReferenceCodec()

function liveDocumentForPath(entry: (typeof referenceContract.reference_paths)[number]) {
  const fixture = referenceContract.fixture_matrix
  const fixtureValue =
    entry.value_kind === 'credential_field' ? fixture.credential_field : fixture.credential_id
  const segments = entry.path.replace(/^\$\./, '').split('.')
  const build = (remaining: string[]): Record<string, unknown> => {
    const [segment, ...rest] = remaining
    const expand = segment.endsWith('[*]')
    const key = expand ? segment.slice(0, -3) : segment
    const child: unknown = rest.length === 0 ? fixtureValue : build(rest)
    return { [key]: expand ? [child] : child }
  }
  const document = build(segments)
  if (entry.path.includes('egress_services')) {
    const service = (document.egress_services as Record<string, unknown>[])[0]
    service.name = 'crm'
    service.base_url = 'https://crm.example.com'
    service.credential_ref ??= fixture.credential_id
    const inject = (service.inject ??= {}) as Record<string, unknown>
    inject.type ??= fixture.inject_type
    inject.credential_field ??= fixture.credential_field
  }
  return document
}

function rawEnvironment() {
  return {
    id: `env_${UUID}`,
    name: 'Environment',
    created_at: '2026-08-06T00:00:00Z',
    updated_at: '2026-08-06T00:00:00Z',
  }
}

describe('environment response parsers', () => {
  it('keeps the production contract projection canonical', () => {
    expect(Object.values(CREDENTIAL_REFERENCE_KEYS)).toEqual(
      referenceContract.canonical_reference_keys,
    )
    expect(CREDENTIAL_REFERENCE_NORMALIZATION.injectType).toBe(
      referenceContract.normalization.inject_type,
    )
    expect(CREDENTIAL_SNAPSHOT_SCHEMAS).toEqual(referenceContract.snapshot_schemas)
    expect(referenceContract.legacy_aliases).toEqual({})
    expect(referenceContract.legacy_decoder_keys).toEqual([])
  })

  it('brands canonical environment and storage volume ids', () => {
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
    expect(() =>
      parseEnvironmentResponse({
        ...rawEnvironment(),
        config: { storage_volumes: [{ volume_id: UUID }] },
      }),
    ).toThrow(TypeError)
  })

  it('brands canonical nested credential ids', () => {
    const environment = parseEnvironmentResponse({
      ...rawEnvironment(),
      config: {
        environment_credential_ids: [`cred_${UUID}`],
        egress_services: [
          {
            name: 'secocean',
            base_url: 'https://secocean.example.com',
            credential_ref: `cred_${UUID}`,
            inject: { type: 'cookie', credential_field: 'COOKIE_HEADER' },
          },
        ],
      },
    })

    expect(environment.config?.environment_credential_ids?.[0]).toBe(`cred_${UUID}`)
    expect(environment.config?.egress_services?.[0].credential_ref).toBe(`cred_${UUID}`)
    expect(environment.config?.egress_services?.[0].inject?.credential_field).toBe('COOKIE_HEADER')
  })

  it.each([
    { secret_refs: [`cred_${UUID}`] },
    { service_credential_id: `cred_${UUID}` },
    {
      egress_services: [
        {
          name: 'secocean',
          base_url: 'https://secocean.example.com',
          service_credential_id: `cred_${UUID}`,
        },
      ],
    },
    {
      egress_services: [
        {
          name: 'secocean',
          base_url: 'https://secocean.example.com',
          credential_ref: `cred_${UUID}`,
          inject: { secret_key: 'TOKEN' },
        },
      ],
    },
  ])('rejects legacy environment credential aliases', (config) => {
    expect(() => parseEnvironmentResponse({ ...rawEnvironment(), config })).toThrow(TypeError)
  })

  it('fails closed for malformed canonical references', () => {
    expect(() =>
      parseEnvironmentResponse({
        ...rawEnvironment(),
        config: { environment_credential_ids: [7] },
      }),
    ).toThrow(TypeError)
    expect(() =>
      parseEnvironmentResponse({
        ...rawEnvironment(),
        config: {
          egress_services: [
            {
              name: 'secocean',
              base_url: 'https://secocean.example.com',
              credential_ref: `cred_${UUID}`,
              inject: { credential_field: '' },
            },
          ],
        },
      }),
    ).toThrow(TypeError)
  })

  it('counts credential field limits by Unicode scalar values', () => {
    const acceptedField = '🔐'.repeat(128)
    const environment = parseEnvironmentResponse({
      ...rawEnvironment(),
      config: {
        egress_services: [
          {
            name: 'secocean',
            base_url: 'https://secocean.example.com',
            credential_ref: `cred_${UUID}`,
            inject: { credential_field: acceptedField },
          },
        ],
      },
    })

    expect(environment.config?.egress_services?.[0].inject?.credential_field).toBe(acceptedField)
    expect(() =>
      parseEnvironmentResponse({
        ...rawEnvironment(),
        config: {
          egress_services: [
            {
              name: 'secocean',
              base_url: 'https://secocean.example.com',
              credential_ref: `cred_${UUID}`,
              inject: { credential_field: '🔐'.repeat(129) },
            },
          ],
        },
      }),
    ).toThrow(TypeError)
  })

  it('treats null canonical reference collections as empty', () => {
    const environment = parseEnvironmentResponse({
      ...rawEnvironment(),
      config: {
        environment_credential_ids: null,
        egress_services: null,
      },
    })

    expect(environment.config?.environment_credential_ids).toEqual([])
    expect(environment.config?.egress_services).toEqual([])
  })

  it('executes every live environment contract path fixture', () => {
    const liveCases = referenceContract.reference_paths.filter(
      (entry) => entry.document === 'environment_config' && entry.schemas.includes('live'),
    )
    expect(liveCases).toHaveLength(3)
    for (const entry of liveCases) {
      const decoded = referenceCodec.decodeEnvironment(liveDocumentForPath(entry))
      if (entry.value_kind === 'credential_id') {
        const credentialIds = [
          ...decoded.direct_credential_ids,
          ...decoded.egress_services.map((service) => service.credential_ref),
        ]
        expect(credentialIds).toContain(referenceContract.fixture_matrix.credential_id)
      } else {
        expect(decoded.egress_services[0]?.inject?.credential_field).toBe(
          referenceContract.fixture_matrix.credential_field,
        )
      }
    }
  })

  it('executes shared live-environment parity vectors', () => {
    for (const vector of referenceContract.parity_vectors.filter(
      (entry) => entry.document === 'environment_config',
    )) {
      const decode = () => {
        const decoded = referenceCodec.decodeEnvironment(vector.input)
        const credentialIds = [
          ...decoded.direct_credential_ids,
          ...decoded.egress_services.map((service) => service.credential_ref),
        ].sort()
        if ('expected_credential_ids' in vector) {
          expect(credentialIds).toEqual(vector.expected_credential_ids)
        }
        if ('expected_inject_types' in vector) {
          expect(decoded.egress_services.map((service) => service.inject?.type)).toEqual(
            vector.expected_inject_types,
          )
        }
      }
      if (vector.result === 'corrupt_record') {
        expect(decode).toThrow(TypeError)
      } else {
        decode()
      }
    }
  })
})

import { parseCredentialId, parseEnvironmentId, parseStorageVolumeId } from '@/types/entity-id'
import type {
  CanonicalEnvironmentCredentialReferences,
  Environment,
  EnvironmentConfig,
  EnvironmentEgressService,
  EnvironmentEgressServiceInject,
  EnvironmentStorageVolume,
} from '@/types/managed'

import { CREDENTIAL_REFERENCE_KEYS } from './credential-reference-contract'

const SUPPORTED_INJECT_KINDS = new Set(['bearer', 'api_key', 'raw_header', 'cookie'])
const CREDENTIAL_FIELD_MAX_LENGTH = 128
const MODEL_CREDENTIAL_ID = CREDENTIAL_REFERENCE_KEYS.modelCredentialId
const ENVIRONMENT_CREDENTIAL_IDS = CREDENTIAL_REFERENCE_KEYS.environmentCredentialIds
const CREDENTIAL_FIELD = CREDENTIAL_REFERENCE_KEYS.credentialField
const CREDENTIAL_REF = CREDENTIAL_REFERENCE_KEYS.credentialRef
const ENVIRONMENT_CONFIG_KEYS = new Set([
  'type',
  'packages',
  'networking',
  'env_vars',
  ENVIRONMENT_CREDENTIAL_IDS,
  'egress_services',
  'storage_volumes',
  'mount_resources',
])
const EGRESS_SERVICE_KEYS = new Set([
  'name',
  'kind',
  'exposure',
  'base_url',
  CREDENTIAL_REF,
  'inject',
  'allowed_paths',
])
const EGRESS_INJECT_KEYS = new Set(['type', CREDENTIAL_FIELD, 'header', 'cookie_name', 'cookies'])

type RawEnvironmentStorageVolume = Omit<EnvironmentStorageVolume, 'volume_id'> & {
  volume_id?: string
}

type RawEnvironmentConfig = Omit<
  EnvironmentConfig,
  'environment_credential_ids' | 'egress_services' | 'storage_volumes'
> & {
  environment_credential_ids?: unknown
  egress_services?: unknown
  storage_volumes?: RawEnvironmentStorageVolume[]
}

type RawEnvironment = Omit<Environment, 'id' | 'config'> & {
  id: string
  config?: RawEnvironmentConfig
}

function requireObject(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function omitKeys(
  document: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> {
  const result = { ...document }
  for (const key of keys) delete result[key]
  return result
}

function assertAllowedKeys(
  document: Record<string, unknown>,
  allowedKeys: ReadonlySet<string>,
  label: string,
) {
  const unexpected = Object.keys(document).filter((key) => !allowedKeys.has(key))
  if (unexpected.length > 0) {
    throw new TypeError(`${label} contains unsupported fields: ${unexpected.sort().join(', ')}`)
  }
}

function parseReferenceId(value: unknown, label: string) {
  if (typeof value !== 'string') {
    throw new TypeError(`${label} must be a string`)
  }
  return parseCredentialId(value)
}

function parseOptionalReferenceId(document: Record<string, unknown>, key: string, label: string) {
  if (document[key] === undefined || document[key] === null) return undefined
  return parseReferenceId(document[key], label)
}

function parseReferenceList(document: Record<string, unknown>, key: string, label: string) {
  const value = document[key]
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) {
    throw new TypeError(`${label} must be a list or null`)
  }
  return value.map((item, index) => parseReferenceId(item, `${label}[${index}]`))
}

function parseOptionalText(value: unknown, label: string): string | undefined {
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new TypeError(`${label} must be a non-empty string`)
  }
  return value.trim()
}

function parseCredentialField(inject: Record<string, unknown>, injectKind: string, index: number) {
  const field =
    parseOptionalText(inject[CREDENTIAL_FIELD], `HTTP egress credential field[${index}]`) ??
    {
      bearer: 'ACCESS_TOKEN',
      api_key: 'API_KEY',
      raw_header: 'API_KEY',
      cookie: 'COOKIE_HEADER',
    }[injectKind]
  if (field === undefined || [...field].length > CREDENTIAL_FIELD_MAX_LENGTH) {
    throw new TypeError(`HTTP egress credential field[${index}] is invalid`)
  }
  return field
}

function parseEgressServices(value: unknown): EnvironmentEgressService[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) {
    throw new TypeError('HTTP egress services must be a list or null')
  }
  return value.map((rawService, index) => {
    const service = requireObject(rawService, `HTTP egress service[${index}]`)
    assertAllowedKeys(service, EGRESS_SERVICE_KEYS, `HTTP egress service[${index}]`)
    const credentialId = parseOptionalReferenceId(
      service,
      CREDENTIAL_REF,
      `HTTP egress credential id[${index}]`,
    )
    if (credentialId === undefined) {
      throw new TypeError(`HTTP egress credential id[${index}] is required`)
    }

    const rawInject = service.inject
    let inject: EnvironmentEgressServiceInject | undefined
    if (rawInject !== undefined && rawInject !== null) {
      const injectDocument = requireObject(rawInject, `HTTP egress inject[${index}]`)
      assertAllowedKeys(injectDocument, EGRESS_INJECT_KEYS, `HTTP egress inject[${index}]`)
      const rawKind = injectDocument.type ?? 'bearer'
      const injectKind = parseOptionalText(
        rawKind,
        `HTTP egress inject kind[${index}]`,
      )?.toLowerCase()
      if (injectKind === undefined || !SUPPORTED_INJECT_KINDS.has(injectKind)) {
        throw new TypeError(`HTTP egress inject kind[${index}] is unsupported`)
      }
      const credentialField = parseCredentialField(injectDocument, injectKind, index)
      const injectRest = omitKeys(injectDocument, [CREDENTIAL_FIELD])
      inject = {
        ...injectRest,
        type: injectKind,
        credential_field: credentialField,
      } as EnvironmentEgressServiceInject
    }

    const serviceRest = omitKeys(service, [CREDENTIAL_REF, 'inject'])
    return {
      ...serviceRest,
      credential_ref: credentialId,
      ...(inject === undefined ? {} : { inject }),
    } as EnvironmentEgressService
  })
}

export class CredentialReferenceCodec {
  decodeModelCredentialId(raw: unknown) {
    const document = requireObject(raw, 'Model credential reference')
    if (!(MODEL_CREDENTIAL_ID in document)) return undefined
    if (document[MODEL_CREDENTIAL_ID] === null) return null
    return parseReferenceId(document[MODEL_CREDENTIAL_ID], 'Model credential id')
  }

  decodeEnvironment(raw: unknown): CanonicalEnvironmentCredentialReferences {
    const document = requireObject(raw, 'Environment config')
    assertAllowedKeys(document, ENVIRONMENT_CONFIG_KEYS, 'Environment config')
    const directIds = parseReferenceList(
      document,
      ENVIRONMENT_CREDENTIAL_IDS,
      'Environment credential ids',
    )

    return {
      direct_credential_ids: [...new Set(directIds)].sort(),
      egress_services: parseEgressServices(document.egress_services),
    }
  }

  canonicalizeEnvironmentForRead(raw: unknown): EnvironmentConfig {
    const document = requireObject(raw, 'Environment config')
    assertAllowedKeys(document, ENVIRONMENT_CONFIG_KEYS, 'Environment config')
    const decoded = this.decodeEnvironment(document)
    const hasDirectReferences = ENVIRONMENT_CREDENTIAL_IDS in document
    const hasEgressServices = 'egress_services' in document
    const rest = omitKeys(document, [ENVIRONMENT_CREDENTIAL_IDS, 'egress_services'])
    return {
      ...rest,
      ...(hasDirectReferences ? { environment_credential_ids: decoded.direct_credential_ids } : {}),
      ...(hasEgressServices ? { egress_services: decoded.egress_services } : {}),
    } as EnvironmentConfig
  }
}

const credentialReferenceCodec = new CredentialReferenceCodec()

export function parseModelCredentialReference(raw: unknown) {
  return credentialReferenceCodec.decodeModelCredentialId(raw)
}

export function parseEnvironmentResponse(response: unknown): Environment {
  const raw = response as RawEnvironment
  return {
    ...raw,
    id: parseEnvironmentId(raw.id),
    config: raw.config
      ? {
          ...credentialReferenceCodec.canonicalizeEnvironmentForRead(raw.config),
          storage_volumes: raw.config.storage_volumes?.map((volume) => ({
            ...volume,
            volume_id:
              volume.volume_id === undefined ? undefined : parseStorageVolumeId(volume.volume_id),
          })),
        }
      : undefined,
  }
}

export function parseEnvironmentListResponse(response: unknown[]): Environment[] {
  return response.map(parseEnvironmentResponse)
}

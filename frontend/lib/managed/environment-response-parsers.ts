import { parseCredentialId, parseEnvironmentId, parseStorageVolumeId } from '@/types/entity-id'
import type {
  CanonicalEnvironmentCredentialReferences,
  Environment,
  EnvironmentConfig,
  EnvironmentEgressService,
  EnvironmentEgressServiceInject,
  EnvironmentStorageVolume,
} from '@/types/managed'

import {
  CREDENTIAL_REFERENCE_KEYS,
  CREDENTIAL_SNAPSHOT_SCHEMAS,
  LEGACY_SNAPSHOT_REFERENCE_PATHS,
} from './credential-reference-contract'

const SUPPORTED_INJECT_KINDS = new Set(['bearer', 'api_key', 'raw_header', 'cookie'])
const CREDENTIAL_FIELD_MAX_LENGTH = 128
const MODEL_CREDENTIAL_ID = CREDENTIAL_REFERENCE_KEYS.modelCredentialId
const ENVIRONMENT_CREDENTIAL_IDS = CREDENTIAL_REFERENCE_KEYS.environmentCredentialIds
const SERVICE_CREDENTIAL_ID = CREDENTIAL_REFERENCE_KEYS.serviceCredentialId
const CREDENTIAL_FIELD = CREDENTIAL_REFERENCE_KEYS.credentialField
const SECRET_REF = CREDENTIAL_REFERENCE_KEYS.secretRef
const SECRET_REFS = CREDENTIAL_REFERENCE_KEYS.secretRefs
const CREDENTIAL_REF = CREDENTIAL_REFERENCE_KEYS.credentialRef
const SECRET_KEY = CREDENTIAL_REFERENCE_KEYS.secretKey

type RawEnvironmentStorageVolume = Omit<EnvironmentStorageVolume, 'volume_id'> & {
  volume_id?: string
}

type RawEnvironmentConfig = Omit<
  EnvironmentConfig,
  'environment_credential_ids' | 'egress_services' | 'storage_volumes'
> & {
  environment_credential_ids?: unknown
  secret_refs?: unknown
  service_credential_id?: unknown
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

function registeredPathKeyCount(document: unknown, path: string): number {
  const segments = path.replace(/^\$\./, '').split('.')
  let parents: unknown[] = [document]
  for (const segment of segments.slice(0, -1)) {
    const expand = segment.endsWith('[*]')
    const key = expand ? segment.slice(0, -3) : segment
    const children: unknown[] = []
    for (const parent of parents) {
      if (
        typeof parent !== 'object' ||
        parent === null ||
        Array.isArray(parent) ||
        !(key in parent)
      ) {
        continue
      }
      const child = (parent as Record<string, unknown>)[key]
      if (expand) {
        if (Array.isArray(child)) children.push(...child)
      } else {
        children.push(child)
      }
    }
    parents = children
  }
  const terminal = segments.at(-1)
  if (terminal === undefined) return 0
  const terminalKey = terminal.endsWith('[*]') ? terminal.slice(0, -3) : terminal
  return parents.filter(
    (parent) =>
      typeof parent === 'object' &&
      parent !== null &&
      !Array.isArray(parent) &&
      terminalKey in parent,
  ).length
}

function parseReferenceId(value: unknown, label: string) {
  if (typeof value !== 'string') {
    throw new TypeError(`${label} must be a string`)
  }
  return parseCredentialId(value)
}

function parseOptionalAliasId(document: Record<string, unknown>, keys: string[], label: string) {
  const values = keys
    .filter((key) => document[key] !== undefined && document[key] !== null)
    .map((key) => parseReferenceId(document[key], label))
  if (values.length === 0) return undefined
  if (new Set(values).size !== 1) {
    throw new TypeError(`${label} aliases conflict`)
  }
  return values[0]
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
  const values = [CREDENTIAL_FIELD, SECRET_KEY]
    .filter((key) => inject[key] !== undefined && inject[key] !== null)
    .map((key) => parseOptionalText(inject[key], `HTTP egress credential field[${index}]`))
  if (new Set(values).size > 1) {
    throw new TypeError(`HTTP egress credential field[${index}] aliases conflict`)
  }
  const field =
    values[0] ??
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
    const credentialId = parseOptionalAliasId(
      service,
      [SERVICE_CREDENTIAL_ID, CREDENTIAL_REF],
      `HTTP egress credential id[${index}]`,
    )
    if (credentialId === undefined) {
      throw new TypeError(`HTTP egress credential id[${index}] is required`)
    }

    const rawInject = service.inject
    let inject: EnvironmentEgressServiceInject | undefined
    if (rawInject !== undefined && rawInject !== null) {
      const injectDocument = requireObject(rawInject, `HTTP egress inject[${index}]`)
      const rawKind = injectDocument.type ?? 'bearer'
      const injectKind = parseOptionalText(
        rawKind,
        `HTTP egress inject kind[${index}]`,
      )?.toLowerCase()
      if (injectKind === undefined || !SUPPORTED_INJECT_KINDS.has(injectKind)) {
        throw new TypeError(`HTTP egress inject kind[${index}] is unsupported`)
      }
      const credentialField = parseCredentialField(injectDocument, injectKind, index)
      const injectRest = omitKeys(injectDocument, [CREDENTIAL_FIELD, SECRET_KEY])
      inject = {
        ...injectRest,
        type: injectKind,
        credential_field: credentialField,
      } as EnvironmentEgressServiceInject
    }

    const serviceRest = omitKeys(service, [CREDENTIAL_REF, 'inject'])
    return {
      ...serviceRest,
      service_credential_id: credentialId,
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

  decodeSnapshot(raw: unknown) {
    const document = requireObject(raw, 'Snapshot')
    const rawSchema = document.schema ?? null
    const schema = Object.entries(CREDENTIAL_SNAPSHOT_SCHEMAS).find(
      ([, value]) => value === rawSchema,
    )?.[0]
    if (schema === undefined) {
      throw new TypeError('Unknown explicit Snapshot schema')
    }
    if (
      schema === 'v2' &&
      LEGACY_SNAPSHOT_REFERENCE_PATHS.some((path) => registeredPathKeyCount(document, path) > 0)
    ) {
      throw new TypeError('Legacy alias is not allowed in explicit v2 Snapshot')
    }

    const modelCredentialId = parseOptionalAliasId(
      document,
      [MODEL_CREDENTIAL_ID, SECRET_REF],
      'Snapshot model credential id',
    )
    if (modelCredentialId !== undefined) {
      parseOptionalText(document.engine_kind, 'Snapshot engine kind')
    }
    const topLevelIds = [
      ...parseReferenceList(
        document,
        ENVIRONMENT_CREDENTIAL_IDS,
        'Snapshot environment credential ids',
      ),
      ...parseReferenceList(document, SECRET_REFS, 'Snapshot legacy secret refs'),
    ]
    const environment = document.environment
    let nested = {
      direct_credential_ids: [],
      egress_services: [],
    } as CanonicalEnvironmentCredentialReferences
    if (environment !== undefined && environment !== null) {
      const environmentDocument = requireObject(environment, 'Snapshot environment')
      const config = environmentDocument.config
      if (config !== undefined && config !== null) nested = this.decodeEnvironment(config)
    }
    const credentialIds = [
      ...topLevelIds,
      ...nested.direct_credential_ids,
      ...nested.egress_services.map((service) => service.service_credential_id),
      ...(modelCredentialId === undefined ? [] : [modelCredentialId]),
    ]
    return {
      schema,
      credential_ids: [...new Set(credentialIds)].sort(),
      egress_services: nested.egress_services,
    }
  }

  decodeEnvironment(raw: unknown): CanonicalEnvironmentCredentialReferences {
    const document = requireObject(raw, 'Environment config')
    const directIds = [
      ...parseReferenceList(document, ENVIRONMENT_CREDENTIAL_IDS, 'Environment credential ids'),
      ...parseReferenceList(document, SECRET_REFS, 'Environment secret refs'),
    ]
    const legacyServiceId = parseOptionalAliasId(
      document,
      [SERVICE_CREDENTIAL_ID],
      'Environment legacy service credential id',
    )
    if (legacyServiceId !== undefined) directIds.push(legacyServiceId)

    return {
      direct_credential_ids: [...new Set(directIds)].sort(),
      egress_services: parseEgressServices(document.egress_services),
    }
  }

  canonicalizeEnvironmentForRead(raw: unknown): EnvironmentConfig {
    const document = requireObject(raw, 'Environment config')
    const decoded = this.decodeEnvironment(document)
    const hasDirectReferences = [
      ENVIRONMENT_CREDENTIAL_IDS,
      SECRET_REFS,
      SERVICE_CREDENTIAL_ID,
    ].some((key) => key in document)
    const hasEgressServices = 'egress_services' in document
    const rest = omitKeys(document, [
      ENVIRONMENT_CREDENTIAL_IDS,
      SECRET_REFS,
      SERVICE_CREDENTIAL_ID,
      'egress_services',
    ])
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

export function parseEnvironmentListResponse(response: RawEnvironment[]): Environment[] {
  return response.map(parseEnvironmentResponse)
}

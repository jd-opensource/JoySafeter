import { z } from 'zod'

import type {
  LlmCatalog,
  LlmCredentialProfile,
  LlmEngineCapability,
  LlmProtocolDefinition,
  LlmProviderDefinition,
  LlmProviderProtocolOption,
  StableConnectionFingerprintInput,
} from '@/types/llm'

const credentialFieldSchema = z
  .object({
    key: z.string().min(1),
    label: z.string().min(1),
    type: z.enum(['secret', 'text', 'url', 'select']),
    required: z.boolean().default(false),
    placeholder: z.string().nullable().default(null),
    help_text: z.string().nullable().default(null),
    options: z.array(z.string()).default([]),
    advanced: z.boolean().default(false),
  })
  .strict()

const credentialProfileSchema = z
  .object({
    id: z.string().min(1),
    fields: z.array(credentialFieldSchema),
    required_any_of: z.array(z.array(z.string().min(1)).min(1)).default([]),
    base_url_key: z.string().nullable().default(null),
    model_key: z.string().nullable().default(null),
  })
  .strict()

const protocolBindingSchema = z
  .object({
    protocol_id: z.string().min(1),
    credential_profile_id: z.string().min(1),
    default_base_url: z.string().nullable().default(null),
    model_suggestions: z.array(z.string()).default([]),
  })
  .strict()

const engineSchema = z
  .object({
    id: z.string().min(1),
    display_name: z.string().min(1),
    enabled: z.boolean().default(true),
    supported_protocol_ids: z.array(z.string().min(1)),
    preferred_protocol_ids: z.array(z.string().min(1)).default([]),
  })
  .strict()

const protocolSchema = z
  .object({
    id: z.string().min(1),
    display_name: z.string().min(1),
    description: z.string(),
  })
  .strict()

const providerSchema = z
  .object({
    id: z.string().min(1),
    display_name: z.string().min(1),
    enabled: z.boolean().default(true),
    protocol_bindings: z.array(protocolBindingSchema),
  })
  .strict()

const catalogSchema = z
  .object({
    version: z.string().min(1),
    engines: z.array(engineSchema).min(1),
    protocols: z.array(protocolSchema).min(1),
    providers: z.array(providerSchema).min(1),
    credential_profiles: z.array(credentialProfileSchema).min(1),
  })
  .strict()

function ensureUnique(label: string, ids: string[]) {
  const seen = new Set<string>()
  for (const id of ids) {
    if (seen.has(id)) throw new Error(`Duplicate ${label} id: ${id}`)
    seen.add(id)
  }
}

function validateCatalogReferences(catalog: LlmCatalog) {
  ensureUnique(
    'engine',
    catalog.engines.map((engine) => engine.id),
  )
  ensureUnique(
    'protocol',
    catalog.protocols.map((protocol) => protocol.id),
  )
  ensureUnique(
    'provider',
    catalog.providers.map((provider) => provider.id),
  )
  ensureUnique(
    'credential profile',
    catalog.credential_profiles.map((profile) => profile.id),
  )

  const protocolIds = new Set(catalog.protocols.map((protocol) => protocol.id))
  const profileIds = new Set(catalog.credential_profiles.map((profile) => profile.id))
  for (const engine of catalog.engines) {
    for (const protocolId of engine.supported_protocol_ids) {
      if (!protocolIds.has(protocolId)) {
        throw new Error(`Engine ${engine.id} references unknown protocol: ${protocolId}`)
      }
    }
    for (const protocolId of engine.preferred_protocol_ids) {
      if (!engine.supported_protocol_ids.includes(protocolId)) {
        throw new Error(`Engine ${engine.id} prefers unsupported protocol: ${protocolId}`)
      }
    }
  }

  for (const provider of catalog.providers) {
    ensureUnique(
      `protocol binding for provider ${provider.id}`,
      provider.protocol_bindings.map((binding) => binding.protocol_id),
    )
    for (const binding of provider.protocol_bindings) {
      if (!protocolIds.has(binding.protocol_id)) {
        throw new Error(
          `Provider ${provider.id} references unknown protocol: ${binding.protocol_id}`,
        )
      }
      if (!profileIds.has(binding.credential_profile_id)) {
        throw new Error(
          `Provider ${provider.id} references unknown credential profile: ${binding.credential_profile_id}`,
        )
      }
    }
  }

  for (const profile of catalog.credential_profiles) {
    ensureUnique(
      `field for credential profile ${profile.id}`,
      profile.fields.map((field) => field.key),
    )
    const fieldKeys = new Set(profile.fields.map((field) => field.key))
    for (const key of [profile.base_url_key, profile.model_key]) {
      if (key && !fieldKeys.has(key)) {
        throw new Error(`Credential profile ${profile.id} references unknown field: ${key}`)
      }
    }
    for (const group of profile.required_any_of) {
      for (const key of group) {
        if (!fieldKeys.has(key)) {
          throw new Error(`Credential profile ${profile.id} references unknown field: ${key}`)
        }
      }
    }
  }
}

export function parseLlmCatalogResponse(response: unknown): LlmCatalog {
  const catalog = catalogSchema.parse(response) as LlmCatalog
  validateCatalogReferences(catalog)
  return catalog
}

export function getEngine(catalog: LlmCatalog, engineId: string): LlmEngineCapability {
  const engine = catalog.engines.find((item) => item.id === engineId)
  if (!engine) throw new Error(`Unknown LLM engine: ${engineId}`)
  return engine
}

export function getEnabledEngines(catalog: LlmCatalog): LlmEngineCapability[] {
  return catalog.engines.filter((engine) => engine.enabled)
}

export function findProvider(
  catalog: LlmCatalog,
  providerId: string,
): LlmProviderDefinition | null {
  return catalog.providers.find((item) => item.id === providerId) ?? null
}

export function findProtocol(
  catalog: LlmCatalog,
  protocolId: string,
): LlmProtocolDefinition | null {
  return catalog.protocols.find((item) => item.id === protocolId) ?? null
}

export function getProvider(catalog: LlmCatalog, providerId: string): LlmProviderDefinition {
  const provider = catalog.providers.find((item) => item.id === providerId)
  if (!provider) throw new Error(`Unknown LLM provider: ${providerId}`)
  return provider
}

export function getProtocol(catalog: LlmCatalog, protocolId: string): LlmProtocolDefinition {
  const protocol = catalog.protocols.find((item) => item.id === protocolId)
  if (!protocol) throw new Error(`Unknown LLM protocol: ${protocolId}`)
  return protocol
}

export function getCredentialProfileForBinding(
  catalog: LlmCatalog,
  providerId: string,
  protocolId: string,
): LlmCredentialProfile {
  const profile = findCredentialProfileForBinding(catalog, providerId, protocolId)
  if (!profile) throw new Error(`Provider ${providerId} does not implement protocol ${protocolId}`)
  return profile
}

export function findCredentialProfileForBinding(
  catalog: LlmCatalog,
  providerId: string,
  protocolId: string,
): LlmCredentialProfile | null {
  const provider = findProvider(catalog, providerId)
  const binding = provider?.protocol_bindings.find((item) => item.protocol_id === protocolId)
  if (!binding) return null
  return (
    catalog.credential_profiles.find((item) => item.id === binding.credential_profile_id) ?? null
  )
}

function buildProviderProtocolOptions(
  catalog: LlmCatalog,
  includeProtocol?: (protocolId: string) => boolean,
): LlmProviderProtocolOption[] {
  const options: LlmProviderProtocolOption[] = []
  for (const provider of catalog.providers) {
    if (!provider.enabled) continue
    for (const binding of provider.protocol_bindings) {
      if (includeProtocol && !includeProtocol(binding.protocol_id)) continue
      options.push({
        providerId: provider.id,
        protocolId: binding.protocol_id,
        provider,
        protocol: getProtocol(catalog, binding.protocol_id),
        binding,
        credentialProfile: getCredentialProfileForBinding(
          catalog,
          provider.id,
          binding.protocol_id,
        ),
      })
    }
  }
  return options
}

export function getProviderProtocolOptions(
  catalog: LlmCatalog,
  engineId: string,
): LlmProviderProtocolOption[] {
  const engine = getEngine(catalog, engineId)
  if (!engine.enabled) return []
  const supported = new Set(engine.supported_protocol_ids)
  return buildProviderProtocolOptions(catalog, (protocolId) => supported.has(protocolId))
}

export function getAllProviderProtocolOptions(catalog: LlmCatalog): LlmProviderProtocolOption[] {
  return buildProviderProtocolOptions(catalog)
}

export function stableConnectionFingerprint({
  providerId,
  protocolId,
  values,
}: StableConnectionFingerprintInput): string {
  return JSON.stringify([
    providerId,
    protocolId,
    Object.keys(values)
      .sort()
      .map((key) => [key, values[key]]),
  ])
}

import { z } from 'zod'

import { parseCredentialGroupId, parseCredentialId, parseNullableId } from '@/types/entity-id'
import type { ModelConnectionSummary, Secret, SecretDetail } from '@/types/managed'

const secretBaseSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    kind: z.enum(['model', 'mcp', 'service']),
    provider: z.string().nullable(),
    protocol: z.string().nullable(),
    model: z.string().nullable(),
    compatible_engine_ids: z.array(z.string()),
    is_default: z.boolean(),
    mcp_server_url: z.string().nullable().optional(),
    group_id: z.string().nullable().optional(),
    archived_at: z.string().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict()

const usableSecretDataSchema = z
  .record(z.string(), z.string())
  .default({})
  .transform((data) =>
    Object.fromEntries(Object.entries(data).filter(([field]) => field.trim().length > 0)),
  )

const secretSchema = secretBaseSchema.extend({ data: usableSecretDataSchema }).strict()

const modelConnectionSummarySchema = z
  .object({
    id: z.string(),
    name: z.string(),
    provider: z.string().nullable(),
    protocol: z.string().nullable(),
    model: z.string().nullable(),
    is_default: z.boolean(),
    archived_at: z.string().nullable(),
  })
  .strict()

export function parseModelConnectionSummaryResponse(response: unknown): ModelConnectionSummary {
  const raw = modelConnectionSummarySchema.parse(response)
  return {
    ...raw,
    id: parseCredentialId(raw.id),
  }
}

export function parseSecretResponse(response: unknown): Secret {
  const raw = secretSchema.parse(response)
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    group_id: parseNullableId(raw.group_id ?? null, parseCredentialGroupId),
  }
}

export function parseSecretDetailResponse(response: unknown): SecretDetail {
  const raw = secretSchema.parse(response)
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    group_id: parseNullableId(raw.group_id ?? null, parseCredentialGroupId),
  }
}

export function parseSecretListResponse(response: unknown[]): Secret[] {
  return response.map(parseSecretResponse)
}

export function isSelectableSecretResourceName(name: string): boolean {
  return name.length > 0 && name === name.trim()
}

export function filterSelectableSecretResources<T extends Pick<Secret, 'name'>>(secrets: T[]): T[] {
  return secrets.filter((secret) => isSelectableSecretResourceName(secret.name))
}

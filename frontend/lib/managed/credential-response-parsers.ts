import { z } from 'zod'

import { parseCredentialGroupId, parseCredentialId, parseNullableId } from '@/types/entity-id'
import type { Credential, CredentialDetail, ModelConnectionSummary } from '@/types/managed'

const mcpCredentialAuthSchemeSchema = z.enum(['static_bearer', 'header_api_key', 'custom_header'])

const credentialBaseSchema = z
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
    auth_scheme: mcpCredentialAuthSchemeSchema.nullable().optional().default(null),
    archived_at: z.string().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict()

const usableCredentialDataSchema = z
  .record(z.string(), z.string())
  .default({})
  .transform((data) =>
    Object.fromEntries(Object.entries(data).filter(([field]) => field.trim().length > 0)),
  )

const credentialSchema = credentialBaseSchema.extend({ data: usableCredentialDataSchema }).strict()

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

export function parseCredentialResponse(response: unknown): Credential {
  const raw = credentialSchema.parse(response)
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    group_id: parseNullableId(raw.group_id ?? null, parseCredentialGroupId),
  }
}

export function parseCredentialDetailResponse(response: unknown): CredentialDetail {
  const raw = credentialSchema.parse(response)
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    group_id: parseNullableId(raw.group_id ?? null, parseCredentialGroupId),
  }
}

export function parseCredentialListResponse(response: unknown[]): Credential[] {
  return response.map(parseCredentialResponse)
}

export function isSelectableCredentialName(name: string): boolean {
  return name.length > 0 && name === name.trim()
}

export function filterSelectableCredentials<T extends Pick<Credential, 'name'>>(
  credentials: T[],
): T[] {
  return credentials.filter((credential) => isSelectableCredentialName(credential.name))
}

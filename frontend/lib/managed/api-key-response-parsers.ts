import { z } from 'zod'

import { parseApiKeyId, parseProjectId } from '@/types/entity-id'
import type { ApiKey, ApiKeyCreateResponse } from '@/types/managed'

const apiKeySchema = z
  .object({
    id: z.string(),
    project_id: z.string(),
    name: z.string(),
    key_prefix: z.string(),
    role: z.string(),
    status: z.enum(['active', 'expired', 'revoked']),
    created_at: z.string().optional(),
    expires_at: z.string().nullable().optional(),
    revoked_at: z.string().nullable().optional(),
    last_used_at: z.string().nullable().optional(),
  })
  .strict()

const apiKeyCreateSchema = apiKeySchema.extend({ raw_key: z.string() }).strict()

export function parseApiKeyResponse(response: unknown): ApiKey {
  const raw = apiKeySchema.parse(response)
  return {
    ...raw,
    id: parseApiKeyId(raw.id),
    project_id: parseProjectId(raw.project_id),
  }
}

export function parseApiKeyCreateResponse(response: unknown): ApiKeyCreateResponse {
  const raw = apiKeyCreateSchema.parse(response)
  return {
    ...raw,
    id: parseApiKeyId(raw.id),
    project_id: parseProjectId(raw.project_id),
  }
}

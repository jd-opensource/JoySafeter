import { parseSecretId } from '@/types/entity-id'
import type { Secret, SecretDetail } from '@/types/managed'
import { z } from 'zod'

const secretBaseSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    kind: z.enum(['llm', 'generic']),
    provider: z.string().nullable(),
    protocol: z.string().nullable(),
    model: z.string().nullable(),
    compatible_engine_ids: z.array(z.string()),
    is_default: z.boolean(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict()

const secretListSchema = secretBaseSchema.extend({ keys: z.array(z.string()).default([]) }).strict()
const secretDetailSchema = secretBaseSchema
  .extend({ secret_data: z.record(z.string(), z.string()).default({}) })
  .strict()

export function parseSecretResponse(response: unknown): Secret {
  const raw = secretListSchema.parse(response)
  return { ...raw, id: parseSecretId(raw.id) }
}

export function parseSecretDetailResponse(response: unknown): SecretDetail {
  const raw = secretDetailSchema.parse(response)
  return { ...raw, id: parseSecretId(raw.id) }
}

export function parseSecretListResponse(response: unknown[]): Secret[] {
  return response.map(parseSecretResponse)
}

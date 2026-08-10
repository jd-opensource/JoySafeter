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

const usableSecretFieldNamesSchema = z
  .array(z.string())
  .default([])
  .transform((fields) => fields.filter((field) => field.trim().length > 0))
const usableSecretDataSchema = z
  .record(z.string(), z.string())
  .default({})
  .transform((data) =>
    Object.fromEntries(Object.entries(data).filter(([field]) => field.trim().length > 0)),
  )

const secretListSchema = secretBaseSchema.extend({ keys: usableSecretFieldNamesSchema }).strict()
const secretDetailSchema = secretBaseSchema
  .extend({ secret_data: usableSecretDataSchema })
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

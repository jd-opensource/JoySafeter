import { parseSecretId } from '@/types/entity-id'
import type { Secret, SecretDetail } from '@/types/managed'

type RawSecret = Omit<Secret, 'id'> & { id: string }
type RawSecretDetail = Omit<SecretDetail, 'id'> & { id: string }

export function parseSecretResponse(response: unknown): Secret {
  const raw = response as RawSecret
  return { ...raw, id: parseSecretId(raw.id) }
}

export function parseSecretDetailResponse(response: unknown): SecretDetail {
  const raw = response as RawSecretDetail
  return { ...raw, id: parseSecretId(raw.id) }
}

export function parseSecretListResponse(response: unknown[]): Secret[] {
  return response.map(parseSecretResponse)
}

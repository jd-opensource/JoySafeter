import { parseCredentialGroupId, parseCredentialId } from '@/types/entity-id'
import type { CredentialGroup, CredentialGroupCredential } from '@/types/managed'

type RawCredentialGroup = Omit<CredentialGroup, 'id'> & { id: string }
type RawCredentialGroupCredential = Omit<CredentialGroupCredential, 'id' | 'group_id'> & {
  id: string
  group_id: string
}

export function parseCredentialGroupResponse(response: unknown): CredentialGroup {
  const raw = response as RawCredentialGroup
  return { ...raw, id: parseCredentialGroupId(raw.id) }
}

export function parseCredentialGroupListResponse(response: unknown[]): CredentialGroup[] {
  return response.map(parseCredentialGroupResponse)
}

export function parseCredentialGroupCredentialResponse(
  response: unknown,
): CredentialGroupCredential {
  const raw = response as RawCredentialGroupCredential
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    group_id: parseCredentialGroupId(raw.group_id),
  }
}

export function parseCredentialGroupCredentialListResponse(
  response: unknown[],
): CredentialGroupCredential[] {
  return response.map(parseCredentialGroupCredentialResponse)
}

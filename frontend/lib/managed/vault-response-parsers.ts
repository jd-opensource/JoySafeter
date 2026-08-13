import { parseCredentialGroupId, parseCredentialId } from '@/types/entity-id'
import type { Vault, VaultCredential } from '@/types/managed'

type RawVault = Omit<Vault, 'id'> & { id: string }
type RawVaultCredential = Omit<VaultCredential, 'id' | 'group_id'> & {
  id: string
  group_id: string
}

export function parseVaultResponse(response: unknown): Vault {
  const raw = response as RawVault
  return { ...raw, id: parseCredentialGroupId(raw.id) }
}

export function parseVaultListResponse(response: unknown[]): Vault[] {
  return response.map(parseVaultResponse)
}

export function parseVaultCredentialResponse(response: unknown): VaultCredential {
  const raw = response as RawVaultCredential
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    group_id: parseCredentialGroupId(raw.group_id),
  }
}

export function parseVaultCredentialListResponse(response: unknown[]): VaultCredential[] {
  return response.map(parseVaultCredentialResponse)
}

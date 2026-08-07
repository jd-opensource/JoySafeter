import { parseCredentialId, parseVaultId } from '@/types/entity-id'
import type { Vault, VaultCredential } from '@/types/managed'

type RawVault = Omit<Vault, 'id'> & { id: string }
type RawVaultCredential = Omit<VaultCredential, 'id' | 'vault_id'> & {
  id: string
  vault_id: string
}

export function parseVaultResponse(response: unknown): Vault {
  const raw = response as RawVault
  return { ...raw, id: parseVaultId(raw.id) }
}

export function parseVaultListResponse(response: unknown[]): Vault[] {
  return response.map(parseVaultResponse)
}

export function parseVaultCredentialResponse(response: unknown): VaultCredential {
  const raw = response as RawVaultCredential
  return {
    ...raw,
    id: parseCredentialId(raw.id),
    vault_id: parseVaultId(raw.vault_id),
  }
}

export function parseVaultCredentialListResponse(response: unknown[]): VaultCredential[] {
  return response.map(parseVaultCredentialResponse)
}

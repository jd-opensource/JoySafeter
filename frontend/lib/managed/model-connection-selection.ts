import type { Credential } from '@/types/managed'
import type { CredentialId } from '@/types/entity-id'

export function selectInitialModelConnection(options: Credential[]): CredentialId | '' {
  if (options.length === 1) return options[0].id
  const defaults = options.filter((option) => option.is_default)
  return defaults.length === 1 ? defaults[0].id : ''
}

import { objectValue } from '@/lib/managed/quickstart-value-coercion'

export interface QuickstartVaultRecommendation {
  name: string
  mcpServerUrl: string
  credentialName: string
  requiresCredential: boolean
}

function trimmedString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/**
 * Derives the credential-group fields an AI recommendation produced in Step 4.
 *
 * When the model recommends an `mcp_server_url`, the resulting credential group is
 * only useful once a matching credential member (with a user-supplied token) exists.
 * `requiresCredential` signals that the UI must collect the token before creating the
 * group, so we never create an empty group that falsely looks authorized.
 */
export function quickstartVaultRecommendation(
  vaultConfig: Record<string, unknown> | undefined,
): QuickstartVaultRecommendation {
  const config = objectValue(vaultConfig) ?? {}
  const mcpServerUrl = trimmedString(config.mcp_server_url)
  return {
    name: trimmedString(config.name),
    mcpServerUrl,
    credentialName: trimmedString(config.credential_name),
    requiresCredential: mcpServerUrl !== '',
  }
}

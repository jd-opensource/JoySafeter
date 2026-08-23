export type ApiKeyStatus = 'active' | 'expired' | 'revoked'

export function apiKeyStatusLabelKey(status: ApiKeyStatus): string {
  return `manage.apiKeys.status.${status}`
}

export function canRevokeApiKey(status: ApiKeyStatus): boolean {
  return status !== 'revoked'
}

export function buildApiKeyCreatePayload(name: string, role: string, localExpiry: string) {
  return {
    name,
    role,
    ...(localExpiry ? { expires_at: new Date(localExpiry).toISOString() } : {}),
  }
}

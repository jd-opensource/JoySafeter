export const ANTHROPIC_AUTH_SCHEME = {
  auto: 'auto',
  xapikey: 'xapikey',
  bearer: 'bearer',
} as const

export type AnthropicAuthScheme = (typeof ANTHROPIC_AUTH_SCHEME)[keyof typeof ANTHROPIC_AUTH_SCHEME]

export const ANTHROPIC_ENV = {
  apiKey: 'ANTHROPIC_API_KEY',
  authToken: 'ANTHROPIC_AUTH_TOKEN',
  baseUrl: 'ANTHROPIC_BASE_URL',
} as const

const OFFICIAL_HOST = 'api.anthropic.com'

function hostOf(baseUrl: string): string {
  const raw = (baseUrl || '').trim()
  if (!raw) return ''
  try {
    return new URL(raw.includes('://') ? raw : `http://${raw}`).hostname.toLowerCase()
  } catch {
    return ''
  }
}

export function isOfficialAnthropic(baseUrl: string): boolean {
  const host = hostOf(baseUrl)
  return host === '' || host === OFFICIAL_HOST
}

export function resolveAnthropicScheme(
  baseUrl: string,
  requested: AnthropicAuthScheme,
): typeof ANTHROPIC_AUTH_SCHEME.xapikey | typeof ANTHROPIC_AUTH_SCHEME.bearer {
  if (requested === ANTHROPIC_AUTH_SCHEME.xapikey || requested === ANTHROPIC_AUTH_SCHEME.bearer) {
    return requested
  }
  return isOfficialAnthropic(baseUrl) ? ANTHROPIC_AUTH_SCHEME.xapikey : ANTHROPIC_AUTH_SCHEME.bearer
}

export function inferSchemeFromValues(values: Record<string, string>): AnthropicAuthScheme {
  if ((values[ANTHROPIC_ENV.authToken] || '').trim()) return ANTHROPIC_AUTH_SCHEME.bearer
  if ((values[ANTHROPIC_ENV.apiKey] || '').trim()) return ANTHROPIC_AUTH_SCHEME.xapikey
  return ANTHROPIC_AUTH_SCHEME.auto
}

export type AnthropicAuthScheme = 'auto' | 'xapikey' | 'bearer'

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
): 'xapikey' | 'bearer' {
  if (requested === 'xapikey' || requested === 'bearer') return requested
  return isOfficialAnthropic(baseUrl) ? 'xapikey' : 'bearer'
}

export function inferSchemeFromValues(values: Record<string, string>): AnthropicAuthScheme {
  if ((values.ANTHROPIC_AUTH_TOKEN || '').trim()) return 'bearer'
  if ((values.ANTHROPIC_API_KEY || '').trim()) return 'xapikey'
  return 'auto'
}

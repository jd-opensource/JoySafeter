function normalizeHost(rawValue: string): string | null {
  const trimmed = rawValue.trim().replace(/[),.;\]}>'"]+$/g, '')
  if (!trimmed) return null

  try {
    const parsed = new URL(trimmed.includes('://') ? trimmed : `http://${trimmed}`)
    return parsed.hostname.toLowerCase()
  } catch {
    return null
  }
}

export function normalizeQuickstartAllowedHosts(input: string | string[]): string[] {
  const values = Array.isArray(input) ? input : input.split(',')
  const hosts = new Set<string>()
  for (const value of values) {
    const host = normalizeHost(value)
    if (host) hosts.add(host)
  }
  return [...hosts]
}

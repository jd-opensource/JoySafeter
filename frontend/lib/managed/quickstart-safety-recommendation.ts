export interface QuickstartSafetyRecommendationInput {
  messages: Array<{ role: string; content: string }>
  agentConfig?: Record<string, unknown>
}

export type QuickstartHostRecommendationReason = 'explicitHosts' | 'knownServices' | 'none'
export type QuickstartExternalToolsRecommendationReason = 'mcpServers' | 'credentialIntent' | 'none'

export interface QuickstartSafetyRecommendation {
  recommendedHosts: string[]
  recommendedMcpServerUrls: string[]
  hostReason: QuickstartHostRecommendationReason
  externalToolsRecommended: boolean
  externalToolsReason: QuickstartExternalToolsRecommendationReason
}

const URL_PATTERN = /https?:\/\/[^\s)\]}>"']+/gi
const BARE_HOST_PATTERN =
  /(?<!@)\b([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)\b/gi
const HOST_BLOCKLIST = new Set(['example.com', 'localhost'])

const KNOWN_SERVICE_HOSTS: Array<{ patterns: RegExp[]; hosts: string[] }> = [
  {
    patterns: [/\bgithub\b/i, /\bgit\b/i, /\brepo(?:sitory)?\b/i, /\bpull request\b/i],
    hosts: ['github.com', 'api.github.com'],
  },
  {
    patterns: [/\bslack\b/i],
    hosts: ['slack.com', 'slack-edge.com'],
  },
  {
    patterns: [/\bnotion\b/i],
    hosts: ['api.notion.com'],
  },
  {
    patterns: [/\bjira\b/i, /\batlassian\b/i],
    hosts: ['atlassian.net'],
  },
  {
    patterns: [/\blinear\b/i],
    hosts: ['api.linear.app'],
  },
  {
    patterns: [/\bgoogle sheets\b/i, /\bgoogle drive\b/i],
    hosts: ['sheets.googleapis.com', 'www.googleapis.com'],
  },
]

function normalizeHost(rawValue: string): string | null {
  const trimmed = rawValue.trim().replace(/[),.;\]}>'"]+$/g, '')
  if (!trimmed) return null

  let host = trimmed
  try {
    host = new URL(trimmed).hostname
  } catch {
    host = trimmed
      .replace(/^https?:\/\//i, '')
      .split('/')[0]
      .split(':')[0]
  }

  host = host.toLowerCase().replace(/^www\./, '')
  if (!host.includes('.')) return null
  if (HOST_BLOCKLIST.has(host)) return null
  if (host.endsWith('.local')) return null
  return host
}

function collectStrings(value: unknown, collected: string[] = [], depth = 0): string[] {
  if (depth > 5 || value == null) return collected
  if (typeof value === 'string') {
    collected.push(value)
    return collected
  }
  if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, collected, depth + 1)
    return collected
  }
  if (typeof value === 'object') {
    for (const item of Object.values(value as Record<string, unknown>)) {
      collectStrings(item, collected, depth + 1)
    }
  }
  return collected
}

function hasNonEmptyValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0
  if (value && typeof value === 'object') return Object.keys(value).length > 0
  return Boolean(value)
}

function extractHostsFromText(text: string): string[] {
  const hosts = new Set<string>()
  for (const match of text.matchAll(URL_PATTERN)) {
    const host = normalizeHost(match[0])
    if (host) hosts.add(host)
  }
  for (const match of text.matchAll(BARE_HOST_PATTERN)) {
    const host = normalizeHost(match[1])
    if (host) hosts.add(host)
  }
  return [...hosts]
}

function extractUrlsFromText(text: string): string[] {
  const urls = new Set<string>()
  for (const match of text.matchAll(URL_PATTERN)) {
    try {
      const url = new URL(match[0].trim().replace(/[),.;\]}>'"]+$/g, ''))
      urls.add(url.toString())
    } catch {
      // Ignore malformed URL-like text.
    }
  }
  return [...urls]
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

function inferKnownServiceHosts(text: string): string[] {
  const hosts = new Set<string>()
  for (const service of KNOWN_SERVICE_HOSTS) {
    if (service.patterns.some((pattern) => pattern.test(text))) {
      for (const host of service.hosts) hosts.add(host)
    }
  }
  return [...hosts]
}

export function recommendQuickstartSafetyDefaults(
  input: QuickstartSafetyRecommendationInput,
): QuickstartSafetyRecommendation {
  const userText = input.messages
    .filter((message) => message.role === 'user')
    .map((message) => message.content)
    .join('\n')
  const agentStrings = collectStrings(input.agentConfig)
  const combinedText = [userText, ...agentStrings].filter(Boolean).join('\n')

  const explicitHosts = extractHostsFromText(combinedText)
  const knownServiceHosts = inferKnownServiceHosts(combinedText)
  const recommendedHosts = [...new Set([...explicitHosts, ...knownServiceHosts])].slice(0, 8)

  const mcpServers = input.agentConfig?.mcp_servers
  const recommendedMcpServerUrls = extractUrlsFromText(collectStrings(mcpServers).join('\n')).slice(
    0,
    5,
  )
  const externalToolsRecommended =
    hasNonEmptyValue(mcpServers) ||
    /\bmcp\b|credential group|external tool|tool credential/i.test(combinedText)

  return {
    recommendedHosts,
    recommendedMcpServerUrls,
    hostReason:
      explicitHosts.length > 0
        ? 'explicitHosts'
        : knownServiceHosts.length > 0
          ? 'knownServices'
          : 'none',
    externalToolsRecommended,
    externalToolsReason: hasNonEmptyValue(mcpServers)
      ? 'mcpServers'
      : externalToolsRecommended
        ? 'credentialIntent'
        : 'none',
  }
}

import type { McpServer } from '@/types/managed'

export type McpCredentialCoverageStatus =
  | 'matched'
  | 'optional_anonymous'
  | 'not_required'
  | 'missing_required'
  | 'ambiguous'

export interface McpCredentialCoverageEndpoint {
  name: string
  url: string
  normalizedUrl: string
  authRequirement: 'required' | 'optional' | 'none'
  matchingCredentialCount: number
  status: McpCredentialCoverageStatus
}

export interface McpCredentialCoverageSummary {
  endpoints: McpCredentialCoverageEndpoint[]
  blocking: boolean
}

interface McpCredentialMemberLike {
  mcp_server_url?: string | null
  archived_at?: string | null
}

function nonEmptyString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function normalizeMcpServerUrl(value: unknown): string {
  const trimmed = nonEmptyString(value)
  if (!trimmed) return ''

  try {
    const parsed = new URL(trimmed)
    if (!parsed.hostname) return trimmed

    const scheme = parsed.protocol.slice(0, -1).toLowerCase()
    const userInfo = parsed.username
      ? `${parsed.username}${parsed.password ? `:${parsed.password}` : ''}@`
      : ''
    let path = parsed.pathname
    if (path === '/') path = ''
    else if (path.endsWith('/')) path = path.slice(0, -1)

    return `${scheme}://${userInfo}${parsed.host.toLowerCase()}${path}${parsed.search}`
  } catch {
    return trimmed
  }
}

export function summarizeMcpCredentialCoverage(
  servers: McpServer[] | undefined,
  members: McpCredentialMemberLike[],
): McpCredentialCoverageSummary {
  const credentialCounts = new Map<string, number>()
  for (const member of members) {
    if (member.archived_at) continue
    const normalizedUrl = normalizeMcpServerUrl(member.mcp_server_url)
    if (!normalizedUrl) continue
    credentialCounts.set(normalizedUrl, (credentialCounts.get(normalizedUrl) ?? 0) + 1)
  }

  const endpoints: McpCredentialCoverageEndpoint[] = []
  for (const server of servers ?? []) {
    if (server.type === 'local_stdio') continue
    const normalizedUrl = normalizeMcpServerUrl(server.url)
    const matchingCredentialCount = credentialCounts.get(normalizedUrl) ?? 0
    let status: McpCredentialCoverageStatus
    if (server.auth_requirement === 'none') status = 'not_required'
    else if (matchingCredentialCount > 1) status = 'ambiguous'
    else if (matchingCredentialCount === 1) status = 'matched'
    else if (server.auth_requirement === 'required') status = 'missing_required'
    else status = 'optional_anonymous'

    endpoints.push({
      name: server.name,
      url: server.url,
      normalizedUrl,
      authRequirement: server.auth_requirement,
      matchingCredentialCount,
      status,
    })
  }

  return {
    endpoints,
    blocking: endpoints.some(
      (endpoint) => endpoint.status === 'missing_required' || endpoint.status === 'ambiguous',
    ),
  }
}

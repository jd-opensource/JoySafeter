import type { McpAuthRequirement, McpRemoteTransport, McpServer } from '@/types/managed'
import { isRecord } from '@/lib/managed/quickstart-value-coercion'

export type McpPermissionPolicy = 'always_allow' | 'always_ask'
export type McpServerEntry = McpServer & { policy: McpPermissionPolicy }
export interface NamedMcpServer {
  name: string
}

const REMOTE_TRANSPORTS = new Set<McpRemoteTransport>(['streamable_http', 'sse'])
const AUTH_REQUIREMENTS = new Set<McpAuthRequirement>(['required', 'optional', 'none'])

function recordValue(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid MCP ${label}`)
  }
  return value
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`Invalid MCP ${label}`)
  }
  return value.trim()
}

function stringArray(value: unknown): string[] {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new Error('Invalid MCP args')
  }
  return value.map((item) => item.trim()).filter(Boolean)
}

function stringMap(value: unknown): Record<string, string> {
  if (value === undefined) return {}
  const record = recordValue(value, 'env')
  const entries = Object.entries(record)
  if (entries.some(([, item]) => typeof item !== 'string')) {
    throw new Error('Invalid MCP env')
  }
  return Object.fromEntries(
    entries.map(([key, item]) => [key.trim(), item as string]).filter(([key]) => key),
  )
}

function parseMcpServerConfig(
  value: unknown,
  defaultAuthRequirement?: McpAuthRequirement,
): McpServer {
  const raw = recordValue(value, 'server')
  const name = requiredText(raw.name, 'server name')
  const type = requiredText(raw.type, 'transport')

  if (type === 'local_stdio') {
    if (raw.url !== undefined || raw.auth_requirement !== undefined) {
      throw new Error('Invalid MCP local_stdio fields')
    }
    return {
      type,
      name,
      command: requiredText(raw.command, 'command'),
      args: stringArray(raw.args),
      env: stringMap(raw.env),
    }
  }

  if (!REMOTE_TRANSPORTS.has(type as McpRemoteTransport)) {
    throw new Error('Invalid MCP transport')
  }
  if (raw.command !== undefined || raw.args !== undefined || raw.env !== undefined) {
    throw new Error('Invalid MCP remote fields')
  }
  const authRequirement = raw.auth_requirement ?? defaultAuthRequirement
  if (!AUTH_REQUIREMENTS.has(authRequirement as McpAuthRequirement)) {
    throw new Error('Invalid MCP auth requirement')
  }
  return {
    type: type as McpRemoteTransport,
    name,
    url: requiredText(raw.url, 'server URL'),
    auth_requirement: authRequirement as McpAuthRequirement,
  }
}

export function normalizeMcpServerConfig(value: unknown): McpServer {
  return parseMcpServerConfig(value, 'required')
}

export function parseMcpServerResponseConfig(value: unknown): McpServer {
  return parseMcpServerConfig(value)
}

export function validateUniqueMcpServerName(
  name: string | undefined | null,
  existingServers: NamedMcpServer[],
): string | null {
  const trimmedName = name?.trim()
  if (!trimmedName) return null

  const duplicate = existingServers.some((server) => server.name.trim() === trimmedName)
  return duplicate ? `Duplicate MCP server name: ${trimmedName}` : null
}

export function normalizeMcpServerConfigs(value: unknown): McpServer[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) throw new Error('Invalid MCP server list')
  return value.map(normalizeMcpServerConfig)
}

export function parseMcpServerResponseConfigs(value: unknown): McpServer[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) throw new Error('Invalid MCP server list')
  return value.map(parseMcpServerResponseConfig)
}

export function serializeMcpServerEntries(entries: readonly McpServerEntry[]): McpServer[] {
  return entries.map(({ policy: _policy, ...server }) => normalizeMcpServerConfig(server))
}

export function mcpServerEndpointLabel(server: McpServer): string {
  return server.type === 'local_stdio' ? [server.command, ...server.args].join(' ') : server.url
}

export function parseMcpArgsInput(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function parseMcpEnvInput(value: string): Record<string, string> {
  const env: Record<string, string> = {}
  for (const line of value.split('\n')) {
    if (!line.trim()) continue
    const separator = line.indexOf('=')
    if (separator < 1) throw new Error('MCP environment entries must use KEY=VALUE')
    const key = line.slice(0, separator).trim()
    if (!key) throw new Error('MCP environment variable name must not be blank')
    env[key] = line.slice(separator + 1)
  }
  return env
}

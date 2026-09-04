import {
  summarizeMcpCredentialCoverage,
  type McpCredentialMemberLike,
} from '@/lib/managed/mcp-credential-coverage'
import { normalizeQuickstartAllowedHosts } from '@/lib/managed/quickstart-networking'
import type { Environment, McpServer } from '@/types/managed'

export type QuickstartLaunchAssuranceState =
  | 'required'
  | 'ready'
  | 'enforced'
  | 'recommended'
  | 'not_authorized'
  | 'automatic'

export interface QuickstartLaunchAssurance {
  runtime: QuickstartLaunchAssuranceState
  modelConnection: QuickstartLaunchAssuranceState
  environment: QuickstartLaunchAssuranceState
  externalTools: QuickstartLaunchAssuranceState
  audit: QuickstartLaunchAssuranceState
  requiredHosts: string[]
  needsHardening: boolean
}

export function deriveQuickstartLaunchAssurance({
  hasRuntime,
  hasModelConnection,
  environment,
  recommendedHosts,
  mcpServers,
  credentialGroupMembers,
}: {
  hasRuntime: boolean
  hasModelConnection: boolean
  environment: Environment | null
  recommendedHosts: string[]
  mcpServers: McpServer[]
  credentialGroupMembers: McpCredentialMemberLike[]
}): QuickstartLaunchAssurance {
  const networking = environment?.config?.networking
  const allowedHosts = new Set(normalizeQuickstartAllowedHosts(networking?.allowed_hosts ?? []))
  const requiredHosts = normalizeQuickstartAllowedHosts([
    ...recommendedHosts,
    ...mcpServers.flatMap((server) => (server.type === 'local_stdio' ? [] : [server.url])),
  ])
  const environmentEnforced =
    networking?.type === 'limited' && requiredHosts.every((host) => allowedHosts.has(host))
  const externalToolsAuthorized = !summarizeMcpCredentialCoverage(
    mcpServers,
    credentialGroupMembers,
  ).blocking

  return {
    runtime: hasRuntime ? 'ready' : 'required',
    modelConnection: hasModelConnection ? 'ready' : 'required',
    environment: environmentEnforced ? 'enforced' : 'recommended',
    externalTools: externalToolsAuthorized ? 'ready' : 'not_authorized',
    audit: 'automatic',
    requiredHosts,
    needsHardening: !environmentEnforced || !externalToolsAuthorized,
  }
}

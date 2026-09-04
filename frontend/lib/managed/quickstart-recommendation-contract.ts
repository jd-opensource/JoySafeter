// Mirror of backend/contracts/quickstart_recommendation_contract.json.
// Kept in lockstep by quickstart-recommendation-contract.test.ts (parity assertions
// against the backend JSON). The backend Pydantic schema is frozen against the same
// JSON, so this is the frontend half of the FE/BE agreement.

export const QUICKSTART_PHASES = ['understand', 'design', 'secure', 'prove'] as const
export const QUICKSTART_RECOMMENDATION_PHASES = ['understand', 'secure'] as const
export const QUICKSTART_ARTIFACTS = [
  'engine_plan',
  'agent_blueprint',
  'security_plan',
  'execution_proof',
] as const
export const QUICKSTART_NETWORKING_TYPES = ['limited', 'unrestricted'] as const
export const QUICKSTART_ENGINE_READINESS = ['ready', 'setup_required', 'unavailable'] as const
export const QUICKSTART_HOST_REASONS = ['explicitHosts', 'knownServices', 'none'] as const
export const QUICKSTART_EXTERNAL_TOOLS_REASONS = ['mcpServers', 'credentialIntent'] as const
export const QUICKSTART_MCP_AUTH_REQUIREMENTS = ['required', 'optional'] as const

export type QuickstartPhase = (typeof QUICKSTART_PHASES)[number]
export type QuickstartRecommendationPhase = (typeof QUICKSTART_RECOMMENDATION_PHASES)[number]
export type QuickstartArtifact = (typeof QUICKSTART_ARTIFACTS)[number]
export type QuickstartNetworkingType = (typeof QUICKSTART_NETWORKING_TYPES)[number]
export type QuickstartEngineReadiness = (typeof QUICKSTART_ENGINE_READINESS)[number]
export type QuickstartHostReason = (typeof QUICKSTART_HOST_REASONS)[number]
export type QuickstartExternalToolsReason = (typeof QUICKSTART_EXTERNAL_TOOLS_REASONS)[number]
export type QuickstartMcpAuthRequirement = (typeof QUICKSTART_MCP_AUTH_REQUIREMENTS)[number]

// Response shape returned by POST /v1/quickstart/recommendations (mirrors the
// backend QuickstartRecommendation Pydantic model).
export interface QuickstartEngineOption {
  engine_id: string
  readiness: QuickstartEngineReadiness
  compatible_connection_count: number
}

export interface QuickstartEngineRecommendation {
  recommended_engine_id: string | null
  options: QuickstartEngineOption[]
}

export interface QuickstartEnvironmentRecommendation {
  allowed_hosts: string[]
  host_reason: QuickstartHostReason
}

export interface QuickstartCredentialGroupRecommendation {
  mcp_servers: QuickstartMcpServerRecommendation[]
  external_tools_reason: QuickstartExternalToolsReason
}

export interface QuickstartMcpServerRecommendation {
  name: string
  url: string
  auth_requirement: QuickstartMcpAuthRequirement
}

export interface QuickstartUnderstandRecommendation {
  phase: 'understand'
  engine: QuickstartEngineRecommendation
}

export interface QuickstartSecureRecommendation {
  phase: 'secure'
  environment: QuickstartEnvironmentRecommendation
  credential_group: QuickstartCredentialGroupRecommendation | null
}

export type QuickstartRecommendation =
  | QuickstartUnderstandRecommendation
  | QuickstartSecureRecommendation

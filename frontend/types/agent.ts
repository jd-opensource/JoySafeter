export const ENGINE_KINDS = ['claude_code', 'codex', 'native', 'pi'] as const

export type EngineKind = (typeof ENGINE_KINDS)[number]

export const RUNTIME_KINDS = ['sandbox', 'server'] as const

export type RuntimeKind = (typeof RUNTIME_KINDS)[number]

export function hasBuilderSupport(kind?: string): boolean {
  return ENGINE_KINDS.includes(kind as EngineKind)
}

export interface Agent {
  id: string
  project_id?: string
  name: string
  slug: string
  description: string | null
  avatar: string | null
  status: 'draft' | 'active' | 'archived'
  has_custom_env: boolean
  current_draft_version_id: string | null
  active_release_id: string | null
  engine_kind: EngineKind | null
  runtime_kind: RuntimeKind | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface CreateAgentRequest {
  name: string
  description?: string
  avatar?: string
  engine_kind: EngineKind
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
}

export interface UpdateAgentRequest {
  name?: string
  description?: string
  avatar?: string
  status?: 'draft' | 'active' | 'archived'
}

export interface AgentVersion {
  id: string
  agent_id: string
  version_number: number
  status: 'draft' | 'frozen'
  source_kind: string
  engine_kind: EngineKind
  definition_payload: Record<string, unknown>
  capability_manifest: Record<string, unknown>
  changelog: string | null
  created_by: string
  created_at: string
}

export interface CreateAgentVersionRequest {
  source_kind?: string
  engine_kind: EngineKind
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
  changelog?: string
}

export interface UpdateAgentVersionRequest {
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
  changelog?: string
}

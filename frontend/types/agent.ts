export interface Agent {
  id: string
  workspace_id: string
  name: string
  slug: string
  description: string | null
  avatar: string | null
  status: 'draft' | 'active' | 'archived'
  current_draft_version_id: string | null
  active_release_id: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface CreateAgentRequest {
  name: string
  description?: string
  avatar?: string
  definition_kind: 'prompt' | 'graph' | 'code' | 'hybrid'
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
  definition_kind: 'prompt' | 'graph' | 'code' | 'hybrid'
  definition_payload: Record<string, unknown>
  capability_manifest: Record<string, unknown>
  changelog: string | null
  created_by: string
  created_at: string
}

export interface CreateAgentVersionRequest {
  source_kind?: string
  definition_kind: 'prompt' | 'graph' | 'code' | 'hybrid'
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
  changelog?: string
}

export interface UpdateAgentVersionRequest {
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
  changelog?: string
}

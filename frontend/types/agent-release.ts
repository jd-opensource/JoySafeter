export interface AgentRelease {
  id: string
  agent_version_id: string
  release_number: number
  status: 'building' | 'ready' | 'failed' | 'retired'
  runtime_kind: 'graph' | 'sandbox' | 'hosted' | 'external'
  builder_kind: string | null
  executable_ref: Record<string, unknown> | null
  runtime_binding: Record<string, unknown>
  published_by: string | null
  published_at: string | null
  retired_at: string | null
}

export interface CreateAgentReleaseRequest {
  agent_version_id: string
  runtime_kind: 'graph' | 'sandbox' | 'hosted' | 'external'
  builder_kind?: string
  runtime_binding?: Record<string, unknown>
}

export type RuntimeType = 'claude_code' | 'codex' | 'openclaw' | 'langgraph'
export type AgentStatus = 'idle' | 'working' | 'blocked' | 'error' | 'offline'

export interface CreateAgentRequest {
  workspace_id: string
  name: string
  runtime_type: RuntimeType
  description?: string
  instructions?: string
  skill_ids?: string[]
  custom_env?: Record<string, string>
  runtime_config?: Record<string, unknown>
  max_concurrent_tasks?: number
}

export interface UpdateAgentRequest {
  name?: string
  description?: string
  instructions?: string
  skill_ids?: string[]
  custom_env?: Record<string, string>
  runtime_config?: Record<string, unknown>
  max_concurrent_tasks?: number
}

export const RUNTIME_TYPE_LABELS: Record<RuntimeType, string> = {
  claude_code: 'Claude Code',
  codex: 'Codex',
  openclaw: 'OpenClaw',
  langgraph: 'LangGraph',
}

export const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  idle: 'Idle',
  working: 'Working',
  blocked: 'Blocked',
  error: 'Error',
  offline: 'Offline',
}

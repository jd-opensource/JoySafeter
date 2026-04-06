'use client'

import { API_ENDPOINTS, apiGet, apiPost } from '@/lib/api-client'

export interface RunSummary {
  run_id: string
  status: string
  run_type: string
  agent_name: string
  agent_display_name?: string | null
  source: string
  thread_id?: string | null
  graph_id?: string | null
  title?: string | null
  started_at: string
  finished_at?: string | null
  last_seq: number
  error_code?: string | null
  error_message?: string | null
  last_heartbeat_at?: string | null
  updated_at: string
}

export interface RunSnapshot {
  run_id: string
  status: string
  last_seq: number
  projection: Record<string, unknown>
}

export interface RunEvent {
  seq: number
  event_type: string
  payload: Record<string, unknown>
  trace_id?: string | null
  observation_id?: string | null
  parent_observation_id?: string | null
  created_at: string
}

export interface RunEventsPage {
  run_id: string
  events: RunEvent[]
  next_after_seq: number
}

export interface RunListResponse {
  items: RunSummary[]
}

export interface AgentDefinition {
  agent_name: string
  display_name: string
}

export interface AgentListResponse {
  items: AgentDefinition[]
}

export interface CreateRunPayload {
  agent_name: string
  graph_id?: string | null
  message: string
  thread_id?: string | null
  input?: Record<string, unknown> | null
}

export interface CreateSkillCreatorRunPayload {
  message: string
  graph_id: string
  thread_id?: string | null
  edit_skill_id?: string | null
}

export interface CreateRunResponse {
  run_id: string
  thread_id: string
  status: string
}

export const runService = {
  async createRun(payload: CreateRunPayload): Promise<CreateRunResponse> {
    return apiPost<CreateRunResponse>(API_ENDPOINTS.runs, payload)
  },

  async createSkillCreatorRun(payload: CreateSkillCreatorRunPayload): Promise<CreateRunResponse> {
    return this.createRun({
      agent_name: 'skill_creator',
      graph_id: payload.graph_id,
      message: payload.message,
      thread_id: payload.thread_id,
      input: { edit_skill_id: payload.edit_skill_id },
    })
  },

  async getRun(runId: string): Promise<RunSummary> {
    return apiGet<RunSummary>(`${API_ENDPOINTS.runs}/${runId}`)
  },

  async listRuns(params?: {
    runType?: string
    agentName?: string
    status?: string
    search?: string
    limit?: number
  }): Promise<RunListResponse> {
    const query = new URLSearchParams()
    if (params?.runType) query.set('run_type', params.runType)
    if (params?.agentName) query.set('agent_name', params.agentName)
    if (params?.status) query.set('status', params.status)
    if (params?.search) query.set('search', params.search)
    if (params?.limit) query.set('limit', String(params.limit))
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiGet<RunListResponse>(`${API_ENDPOINTS.runs}${suffix}`)
  },

  async listAgents(): Promise<AgentListResponse> {
    return apiGet<AgentListResponse>(`${API_ENDPOINTS.runs}/agents`)
  },

  async getRunSnapshot(runId: string): Promise<RunSnapshot> {
    return apiGet<RunSnapshot>(`${API_ENDPOINTS.runs}/${runId}/snapshot`)
  },

  async getRunEvents(runId: string, params?: { afterSeq?: number; limit?: number }): Promise<RunEventsPage> {
    const afterSeq = params?.afterSeq ?? 0
    const limit = params?.limit ?? 500
    return apiGet<RunEventsPage>(
      `${API_ENDPOINTS.runs}/${runId}/events?after_seq=${afterSeq}&limit=${limit}`,
    )
  },

  async findActiveRun(params: {
    agentName: string
    graphId?: string | null
    threadId?: string | null
  }): Promise<RunSummary | null> {
    const query = new URLSearchParams({
      agent_name: params.agentName,
    })
    if (params.graphId) query.set('graph_id', params.graphId)
    if (params.threadId) query.set('thread_id', params.threadId)
    return apiGet<RunSummary | null>(`${API_ENDPOINTS.runs}/active?${query.toString()}`)
  },

  async findActiveSkillCreatorRun(params: { graphId: string; threadId?: string | null }): Promise<RunSummary | null> {
    return this.findActiveRun({
      agentName: 'skill_creator',
      graphId: params.graphId,
      threadId: params.threadId,
    })
  },

  async findActiveChatRun(params: { threadId: string }): Promise<RunSummary | null> {
    return this.findActiveRun({
      agentName: 'chat',
      threadId: params.threadId,
    })
  },

  async cancelRun(runId: string): Promise<RunSummary> {
    return apiPost<RunSummary>(`${API_ENDPOINTS.runs}/${runId}/cancel`, {})
  },
}

'use client'

import { API_ENDPOINTS, apiGet, apiPost } from '@/lib/api-client'

export interface RunSummary {
  run_id: string
  status: string
  run_type: string
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
  projection: Record<string, any>
}

export interface RunEvent {
  seq: number
  event_type: string
  payload: Record<string, any>
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
  async createSkillCreatorRun(payload: CreateSkillCreatorRunPayload): Promise<CreateRunResponse> {
    return apiPost<CreateRunResponse>(`${API_ENDPOINTS.runs}/skill-creator`, payload)
  },

  async getRun(runId: string): Promise<RunSummary> {
    return apiGet<RunSummary>(`${API_ENDPOINTS.runs}/${runId}`)
  },

  async listRuns(params?: {
    runType?: string
    status?: string
    limit?: number
  }): Promise<RunListResponse> {
    const query = new URLSearchParams()
    if (params?.runType) query.set('run_type', params.runType)
    if (params?.status) query.set('status', params.status)
    if (params?.limit) query.set('limit', String(params.limit))
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiGet<RunListResponse>(`${API_ENDPOINTS.runs}${suffix}`)
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

  async findActiveSkillCreatorRun(params: { graphId: string; threadId?: string | null }): Promise<RunSummary | null> {
    const query = new URLSearchParams({ graph_id: params.graphId })
    if (params.threadId) query.set('thread_id', params.threadId)
    return apiGet<RunSummary | null>(`${API_ENDPOINTS.runs}/active/skill-creator?${query.toString()}`)
  },

  async cancelRun(runId: string): Promise<RunSummary> {
    return apiPost<RunSummary>(`${API_ENDPOINTS.runs}/${runId}/cancel`, {})
  },
}

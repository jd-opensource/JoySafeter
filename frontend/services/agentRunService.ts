'use client'

import { apiGet, apiPost } from '@/lib/api-client'
import type { AgentRun, CreateAgentRunRequest, Execution, ExecutionEvent } from '@/types/agent-run'

export const agentRunService = {
  list: async (params: {
    workspace_id?: string
    release_id?: string
    mission_id?: string
  }): Promise<AgentRun[]> => {
    const searchParams = new URLSearchParams()
    if (params.workspace_id) searchParams.set('workspace_id', params.workspace_id)
    if (params.release_id) searchParams.set('release_id', params.release_id)
    if (params.mission_id) searchParams.set('mission_id', params.mission_id)
    const res = await apiGet<AgentRun[]>(`runs?${searchParams}`)
    return res ?? []
  },

  get: async (runId: string): Promise<AgentRun> => {
    return apiGet<AgentRun>(`runs/${runId}`)
  },

  create: async (data: CreateAgentRunRequest): Promise<AgentRun> => {
    return apiPost<AgentRun>('runs', data)
  },

  cancel: async (runId: string): Promise<AgentRun> => {
    return apiPost<AgentRun>(`runs/${runId}/cancel`, {})
  },

  retry: async (runId: string): Promise<AgentRun> => {
    return apiPost<AgentRun>(`runs/${runId}/retry`, {})
  },

  listExecutions: async (runId: string): Promise<Execution[]> => {
    const res = await apiGet<Execution[]>(`executions?run_id=${runId}`)
    return res ?? []
  },

  getExecution: async (executionId: string): Promise<Execution> => {
    return apiGet<Execution>(`executions/${executionId}`)
  },

  listExecutionEvents: async (executionId: string): Promise<ExecutionEvent[]> => {
    const res = await apiGet<ExecutionEvent[]>(`executions/${executionId}/events`)
    return res ?? []
  },
}

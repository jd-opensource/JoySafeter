'use client'

import { apiGet, apiPost, apiPatch } from '@/lib/api-client'
import type { ExecutionSnapshot, ExecutionEventsPage } from '@/types/agent-run'
import type { Task, CreateTaskRequest, UpdateTaskRequest } from '@/types/tasks'

export interface TaskListResponse {
  items: Task[]
}

export const taskService = {
  list: async (
    workspaceId: string,
    params?: { status?: string; limit?: number; agent_id?: string },
  ): Promise<Task[]> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.status) searchParams.set('status', params.status)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    if (params?.agent_id) searchParams.set('agent_id', params.agent_id)
    const res = await apiGet<{ items: Task[] }>(`tasks?${searchParams}`)
    return res?.items ?? []
  },

  get: async (taskId: string, workspaceId: string): Promise<Task> => {
    return apiGet<Task>(`tasks/${taskId}?workspace_id=${workspaceId}`)
  },

  create: async (data: CreateTaskRequest): Promise<Task> => {
    return apiPost<Task>('tasks', data)
  },

  update: async (taskId: string, workspaceId: string, data: UpdateTaskRequest): Promise<Task> => {
    return apiPatch<Task>(`tasks/${taskId}?workspace_id=${workspaceId}`, data)
  },

  assign: async (taskId: string, workspaceId: string, agentId: string): Promise<Task> => {
    return apiPost<Task>(`tasks/${taskId}/assign?workspace_id=${workspaceId}`, {
      agent_id: agentId,
    })
  },

  dispatch: async (taskId: string, workspaceId: string): Promise<Task> => {
    return apiPost<Task>(`tasks/${taskId}/dispatch?workspace_id=${workspaceId}`, {})
  },

  cancel: async (taskId: string, workspaceId: string): Promise<Task> => {
    return apiPost<Task>(`tasks/${taskId}/cancel?workspace_id=${workspaceId}`, {})
  },

  getTransitions: async (workspaceId: string): Promise<Record<string, string[]>> => {
    return apiGet<Record<string, string[]>>(`tasks/meta/transitions?workspace_id=${workspaceId}`)
  },

  // --- Task-scoped execution operations ---

  getExecutionEvents: async (
    taskId: string,
    workspaceId: string,
    afterSeq?: number,
  ): Promise<ExecutionEventsPage> => {
    const params = new URLSearchParams({ workspace_id: workspaceId })
    if (afterSeq !== undefined) params.set('after_seq', String(afterSeq))
    return apiGet<ExecutionEventsPage>(`tasks/${taskId}/execution/events?${params}`)
  },

  getExecutionSnapshot: async (taskId: string, workspaceId: string): Promise<ExecutionSnapshot> => {
    return apiGet<ExecutionSnapshot>(
      `tasks/${taskId}/execution/snapshot?workspace_id=${workspaceId}`,
    )
  },

  injectExecutionMessage: async (
    taskId: string,
    workspaceId: string,
    message: string,
  ): Promise<void> => {
    await apiPost(`tasks/${taskId}/execution/message?workspace_id=${workspaceId}`, {
      message,
    })
  },

  approveExecutionAction: async (
    taskId: string,
    workspaceId: string,
    approved: boolean,
  ): Promise<void> => {
    await apiPost(`tasks/${taskId}/execution/approve?workspace_id=${workspaceId}`, {
      approved,
    })
  },
}

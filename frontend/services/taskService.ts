'use client'

import { apiGet, apiPost, apiPatch } from '@/lib/api-client'
import type { ExecutionSnapshot, ExecutionEventsPage } from '@/types/agent-run'
import type { Task, CreateTaskRequest, UpdateTaskRequest } from '@/types/tasks'

export interface TaskListResponse {
  items: Task[]
}

export const taskService = {
  list: async (
    params?: { status?: string; limit?: number; agent_id?: string },
  ): Promise<Task[]> => {
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.set('status', params.status)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    if (params?.agent_id) searchParams.set('agent_id', params.agent_id)
    const res = await apiGet<{ items: Task[] }>(`tasks?${searchParams}`)
    return res?.items ?? []
  },

  get: async (taskId: string): Promise<Task> => {
    return apiGet<Task>(`tasks/${taskId}`)
  },

  create: async (data: CreateTaskRequest): Promise<Task> => {
    return apiPost<Task>('tasks', data)
  },

  update: async (taskId: string, data: UpdateTaskRequest): Promise<Task> => {
    return apiPatch<Task>(`tasks/${taskId}`, data)
  },

  assign: async (taskId: string, agentId: string): Promise<Task> => {
    return apiPost<Task>(`tasks/${taskId}/assign`, {
      agent_id: agentId,
    })
  },

  dispatch: async (taskId: string): Promise<Task> => {
    return apiPost<Task>(`tasks/${taskId}/dispatch`, {})
  },

  cancel: async (taskId: string): Promise<Task> => {
    return apiPost<Task>(`tasks/${taskId}/cancel`, {})
  },

  getTransitions: async (): Promise<Record<string, string[]>> => {
    return apiGet<Record<string, string[]>>(`tasks/meta/transitions`)
  },

  // --- Task-scoped execution operations ---

  getExecutionEvents: async (
    taskId: string,
    afterSeq?: number,
  ): Promise<ExecutionEventsPage> => {
    const params = new URLSearchParams()
    if (afterSeq !== undefined) params.set('after_seq', String(afterSeq))
    return apiGet<ExecutionEventsPage>(`tasks/${taskId}/execution/events?${params}`)
  },

  getExecutionSnapshot: async (taskId: string): Promise<ExecutionSnapshot> => {
    return apiGet<ExecutionSnapshot>(
      `tasks/${taskId}/execution/snapshot`,
    )
  },

  injectExecutionMessage: async (
    taskId: string,
    message: string,
  ): Promise<void> => {
    await apiPost(`tasks/${taskId}/execution/message`, {
      message,
    })
  },

  approveExecutionAction: async (
    taskId: string,
    approved: boolean,
  ): Promise<void> => {
    await apiPost(`tasks/${taskId}/execution/approve`, {
      approved,
    })
  },
}

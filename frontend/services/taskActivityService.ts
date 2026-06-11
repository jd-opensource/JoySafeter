import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type {
  TaskActivity,
  CreateTaskActivityRequest,
  TaskActivityListResponse,
} from '@/types/task-activities'

export const taskActivityService = {
  list: async (
    taskId: string,
    params?: { cursor?: string; limit?: number },
  ): Promise<TaskActivityListResponse> => {
    const searchParams = new URLSearchParams()
    if (params?.cursor) searchParams.set('cursor', params.cursor)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    return apiGet<TaskActivityListResponse>(`tasks/${taskId}/activities?${searchParams}`)
  },

  create: async (
    taskId: string,
    data: CreateTaskActivityRequest,
  ): Promise<TaskActivity> => {
    return apiPost<TaskActivity>(`tasks/${taskId}/activities`, data)
  },

  update: async (
    taskId: string,
    activityId: string,
    content: string,
  ): Promise<TaskActivity> => {
    return apiPatch<TaskActivity>(
      `tasks/${taskId}/activities/${activityId}`,
      { content },
    )
  },

  delete: async (taskId: string, activityId: string): Promise<void> => {
    return apiDelete(`tasks/${taskId}/activities/${activityId}`)
  },
}

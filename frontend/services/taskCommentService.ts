import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type {
  MissionComment,
  CreateMissionCommentRequest,
  MissionCommentListResponse,
} from '@/types/mission-comments'

export const taskCommentService = {
  list: async (
    taskId: string,
    workspaceId: string,
    params?: { cursor?: string; limit?: number },
  ): Promise<MissionCommentListResponse> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.cursor) searchParams.set('cursor', params.cursor)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    return apiGet<MissionCommentListResponse>(`tasks/${taskId}/comments?${searchParams}`)
  },

  create: async (
    taskId: string,
    workspaceId: string,
    data: CreateMissionCommentRequest,
  ): Promise<MissionComment> => {
    return apiPost<MissionComment>(
      `tasks/${taskId}/comments?workspace_id=${workspaceId}`,
      data,
    )
  },

  update: async (
    taskId: string,
    commentId: string,
    workspaceId: string,
    content: string,
  ): Promise<MissionComment> => {
    return apiPatch<MissionComment>(
      `tasks/${taskId}/comments/${commentId}?workspace_id=${workspaceId}`,
      { content },
    )
  },

  delete: async (taskId: string, commentId: string, workspaceId: string): Promise<void> => {
    return apiDelete(`tasks/${taskId}/comments/${commentId}?workspace_id=${workspaceId}`)
  },
}

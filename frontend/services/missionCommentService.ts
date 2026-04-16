import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'
import type {
  MissionComment,
  CreateMissionCommentRequest,
  MissionCommentListResponse,
} from '@/types/mission-comments'

export const missionCommentService = {
  list: async (
    missionId: string,
    workspaceId: string,
    params?: { cursor?: string; limit?: number },
  ): Promise<MissionCommentListResponse> => {
    const searchParams = new URLSearchParams({ workspace_id: workspaceId })
    if (params?.cursor) searchParams.set('cursor', params.cursor)
    if (params?.limit) searchParams.set('limit', String(params.limit))
    return apiGet<MissionCommentListResponse>(
      `missions/${missionId}/comments?${searchParams}`,
    )
  },

  create: async (
    missionId: string,
    workspaceId: string,
    data: CreateMissionCommentRequest,
  ): Promise<MissionComment> => {
    return apiPost<MissionComment>(
      `missions/${missionId}/comments?workspace_id=${workspaceId}`,
      data,
    )
  },

  update: async (
    missionId: string,
    commentId: string,
    workspaceId: string,
    content: string,
  ): Promise<MissionComment> => {
    return apiPatch<MissionComment>(
      `missions/${missionId}/comments/${commentId}?workspace_id=${workspaceId}`,
      { content },
    )
  },

  delete: async (
    missionId: string,
    commentId: string,
    workspaceId: string,
  ): Promise<void> => {
    return apiDelete(`missions/${missionId}/comments/${commentId}?workspace_id=${workspaceId}`)
  },
}

'use client'

/**
 * Workspace Service
 *
 * Encapsulates workspace-related API calls, including:
 * - Member management (get, add, update role, remove)
 * - User search
 */

import { API_ENDPOINTS, apiGet, apiPost, apiPatch, apiFetch } from '@/lib/api-client'

// ==================== Types ====================

export interface WorkspaceMember {
  id: string
  userId: string
  email: string
  name: string | null
  role: 'owner' | 'admin' | 'member' | 'viewer'
  isOwner: boolean
  createdAt?: string | null
}

export interface PaginatedMembersResponse {
  items: WorkspaceMember[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface SearchedUser {
  id: string
  email: string
  name: string | null
  image: string | null
}

// ==================== Service ====================

export const workspaceService = {
  // ==================== Member Management ====================

  /**
   * Get workspace member list
   */
  async getMembers(
    workspaceId: string,
    params?: { page?: number; pageSize?: number },
  ): Promise<PaginatedMembersResponse> {
    const { page = 1, pageSize = 10 } = params || {}
    return apiGet<PaginatedMembersResponse>(
      `${API_ENDPOINTS.workspaces}/${workspaceId}/members?page=${page}&page_size=${pageSize}`,
    )
  },

  /**
   * Search users (for adding members)
   */
  async searchUsers(
    workspaceId: string,
    keyword: string,
    limit: number = 10,
  ): Promise<{ users: SearchedUser[] }> {
    if (!keyword.trim() || keyword.length < 2) {
      return { users: [] }
    }
    return apiGet<{ users: SearchedUser[] }>(
      `${API_ENDPOINTS.workspaces}/${workspaceId}/search-users?keyword=${encodeURIComponent(keyword)}&limit=${limit}`,
    )
  },

  /**
   * Add member directly to workspace
   */
  async addMember(
    workspaceId: string,
    email: string,
    role: string,
  ): Promise<{ member: WorkspaceMember }> {
    return apiPost<{ member: WorkspaceMember }>(
      `${API_ENDPOINTS.workspaces}/${workspaceId}/members`,
      { email, role },
    )
  },

  /**
   * Update member role
   */
  async updateMemberRole(
    workspaceId: string,
    userId: string,
    role: string,
  ): Promise<{ member: WorkspaceMember }> {
    return apiPatch<{ member: WorkspaceMember }>(`${API_ENDPOINTS.workspaces}/members/${userId}`, {
      workspaceId,
      role,
    })
  },

  /**
   * Remove member
   */
  async removeMember(workspaceId: string, userId: string): Promise<{ success: boolean }> {
    return apiFetch<{ success: boolean }>(`${API_ENDPOINTS.workspaces}/members/${userId}`, {
      method: 'DELETE',
      body: {
        workspaceId,
      },
    })
  },
}

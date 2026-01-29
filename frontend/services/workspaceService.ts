'use client'

/**
 * Workspace Service
 *
 * Encapsulates workspace-related API calls, including:
 * - Member management (get, update role, remove)
 * - Invitation management (send, accept, reject, query)
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

export interface Invitation {
  id: string
  workspaceId: string
  workspaceName: string
  email: string
  inviterName: string | null
  inviterEmail: string | null
  role: string
  status: string
  permissions: string
  expiresAt: string
  createdAt: string
  isExpired?: boolean
}

export interface PaginatedInvitationsResponse {
  items: Invitation[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface InvitationResponse {
  success: boolean
  invitation: Invitation
}

export interface AcceptInvitationResponse {
  success: boolean
  workspace: {
    id: string
    name: string
  }
  message: string
}

export interface RejectInvitationResponse {
  success: boolean
  message: string
}

// ==================== Service ====================

export const workspaceService = {
  // ==================== Member Management ====================

  /**
   * Get workspace member list
   */
  async getMembers(
    workspaceId: string,
    params?: { page?: number; pageSize?: number }
  ): Promise<PaginatedMembersResponse> {
    const { page = 1, pageSize = 10 } = params || {}
    return apiGet<PaginatedMembersResponse>(
      `${API_ENDPOINTS.workspaces}/${workspaceId}/members?page=${page}&page_size=${pageSize}`
    )
  },

  /**
   * Search users (for invitation search)
   */
  async searchUsers(
    workspaceId: string,
    keyword: string,
    limit: number = 10
  ): Promise<{ users: SearchedUser[] }> {
    if (!keyword.trim() || keyword.length < 2) {
      return { users: [] }
    }
    return apiGet<{ users: SearchedUser[] }>(
      `${API_ENDPOINTS.workspaces}/${workspaceId}/search-users?keyword=${encodeURIComponent(keyword)}&limit=${limit}`
    )
  },

  /**
   * Update member role
   */
  async updateMemberRole(
    workspaceId: string,
    userId: string,
    role: string
  ): Promise<{ member: WorkspaceMember }> {
    return apiPatch<{ member: WorkspaceMember }>(
      `${API_ENDPOINTS.workspaces}/members/${userId}`,
      {
        workspaceId,
        role,
      }
    )
  },

  /**
   * Remove member
   */
  async removeMember(workspaceId: string, userId: string): Promise<{ success: boolean }> {
    return apiFetch<{ success: boolean }>(
      `${API_ENDPOINTS.workspaces}/members/${userId}`,
      {
        method: 'DELETE',
        body: {
          workspaceId,
        },
      }
    )
  },

  // ==================== Invitation Management ====================

  /**
   * Get pending invitations
   */
  async getPendingInvitations(): Promise<{ invitations: Invitation[] }> {
    return apiGet<{ invitations: Invitation[] }>(
      `${API_ENDPOINTS.workspaces}/invitations/pending`
    )
  },

  /**
   * Get all invitations (paginated)
   */
  async getAllInvitations(params?: {
    page?: number
    pageSize?: number
    status?: 'pending' | 'processed'
  }): Promise<PaginatedInvitationsResponse> {
    const { page = 1, pageSize = 10, status } = params || {}
    let url = `${API_ENDPOINTS.workspaces}/invitations/all?page=${page}&page_size=${pageSize}`
    if (status) {
      url += `&status=${status}`
    }
    return apiGet<PaginatedInvitationsResponse>(url)
  },

  /**
   * Get invitation details (via token)
   */
  async getInvitation(token: string): Promise<InvitationResponse> {
    return apiGet<InvitationResponse>(
      `${API_ENDPOINTS.workspaces}/invitations/${token}`
    )
  },

  /**
   * Send invitation
   */
  async sendInvitation(params: {
    workspaceId: string
    email: string
    role: string
    permission?: string
  }): Promise<{ success: boolean; invitation: any }> {
    const permissionMap: Record<string, string> = {
      admin: 'admin',
      member: 'write',
      viewer: 'read',
    }
    const permission = params.permission || permissionMap[params.role] || 'write'

    return apiPost<{ success: boolean; invitation: any }>(
      `${API_ENDPOINTS.workspaces}/invitations`,
      {
        workspaceId: params.workspaceId,
        email: params.email,
        role: params.role,
        permission,
      }
    )
  },

  /**
   * Accept invitation
   */
  async acceptInvitation(invitationIdOrToken: string): Promise<AcceptInvitationResponse> {
    return apiPost<AcceptInvitationResponse>(
      `${API_ENDPOINTS.workspaces}/invitations/${invitationIdOrToken}/accept`
    )
  },

  /**
   * Reject invitation
   */
  async rejectInvitation(invitationId: string): Promise<RejectInvitationResponse> {
    return apiPost<RejectInvitationResponse>(
      `${API_ENDPOINTS.workspaces}/invitations/${invitationId}/reject`
    )
  },
}

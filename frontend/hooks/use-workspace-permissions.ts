/**
 * Workspace Permissions Hook
 *
 * Uses React Query to manage workspace permission data
 * - Automatic caching and request deduplication
 * - Avoids multiple components requesting the same data simultaneously
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import { API_ENDPOINTS, apiGet } from '@/lib/api-client'
import { useSession } from '@/lib/auth/auth-client'
import { createLogger } from '@/lib/logs/console/logger'
import type { PermissionType, WorkspaceMemberRole } from '@/lib/workspaces/permissions/types'
import { mapRoleToPermissionType } from '@/lib/workspaces/permissions/types'

const logger = createLogger('useWorkspacePermissions')

// ============================================================================
// Types
// ============================================================================

/**
 * Member data format returned by backend
 */
interface WorkspaceMemberResponse {
  id: string
  userId: string
  workspaceId: string
  email: string
  name: string | null
  role: 'owner' | 'admin' | 'member' | 'viewer'
  isOwner: boolean
  createdAt?: string | null
  updatedAt?: string | null
}

export interface WorkspaceUser {
  userId: string
  email: string
  name: string | null
  image: string | null
  permissionType: PermissionType
  isOwner: boolean
  role: WorkspaceMemberRole
}

export interface WorkspacePermissions {
  users: WorkspaceUser[]
  total: number
}

interface UseWorkspacePermissionsReturn {
  permissions: WorkspacePermissions | null
  loading: boolean
  error: string | null
  updatePermissions: (newPermissions: WorkspacePermissions) => void
  refetch: () => Promise<void>
}

// ============================================================================
// Query Key Factory
// ============================================================================

export const workspacePermissionKeys = {
  all: ['workspace-permissions'] as const,
  detail: (workspaceId: string) => [...workspacePermissionKeys.all, workspaceId] as const,
}

// ============================================================================
// Fetch Function
// ============================================================================

/**
 * Fetch workspace member list and convert to permission format
 * Used only for backward compatibility; prefer fetchMyPermission for permission checks
 */
async function fetchWorkspacePermissions(workspaceId: string): Promise<WorkspacePermissions> {
  const result = await apiGet<{
    items: WorkspaceMemberResponse[]
    total: number
    pages: number
  }>(`${API_ENDPOINTS.workspaces}/${workspaceId}/members?page=1&page_size=100`)

  const members = result.items || []

  const users: WorkspaceUser[] = members.map((member) => ({
    userId: member.userId,
    email: member.email,
    name: member.name,
    image: null,
    permissionType: mapRoleToPermissionType(member.role),
    isOwner: member.isOwner,
    role: member.role,
  }))

  return {
    users,
    total: users.length,
  }
}

/**
 * Fetch current user's permission only (lightweight)
 * Reuses existing types and mapping logic
 */
async function fetchMyPermission(
  workspaceId: string,
  userEmail: string,
  userId: string,
  userName: string | null = null,
): Promise<WorkspacePermissions> {
  // 复用现有的 API_ENDPOINTS 和 apiGet
  const result = await apiGet<{
    role: 'owner' | 'admin' | 'member' | 'viewer'
    permissionType: 'read' | 'write' | 'admin'
    isOwner: boolean
  }>(`${API_ENDPOINTS.workspaces}/${workspaceId}/my-permission`)

  // 复用现有的 mapRoleToPermissionType 函数
  const users: WorkspaceUser[] = [
    {
      userId: userId,
      email: userEmail,
      name: userName,
      image: null,
      permissionType: mapRoleToPermissionType(result.role),
      isOwner: result.isOwner,
      role: result.role,
    },
  ]

  return {
    users,
    total: 1,
  }
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Custom hook to fetch and manage workspace permissions
 *
 * Always uses lightweight /my-permission endpoint.
 * For full member lists, use workspaceService.getMembers() directly (e.g. in members page).
 *
 * @param workspaceId - The workspace ID to fetch permissions for
 * @returns Object containing permissions data, loading state, error state, and refetch function
 */
export function useWorkspacePermissions(workspaceId: string | null): UseWorkspacePermissionsReturn {
  const queryClient = useQueryClient()
  const { data: session } = useSession()

  const fetchFn = useMemo(() => {
    const userEmail = session?.user?.email
    const userId = session?.user?.id || ''
    const userName = session?.user?.name || null

    if (!userEmail) {
      throw new Error('User session not found')
    }

    return () => fetchMyPermission(workspaceId!, userEmail, userId, userName)
  }, [workspaceId, session])

  const {
    data,
    isLoading,
    error,
    refetch: queryRefetch,
  } = useQuery({
    queryKey: [...workspacePermissionKeys.detail(workspaceId || ''), 'my-permission'],
    queryFn: fetchFn,
    enabled: !!workspaceId && !!session?.user?.email,
    staleTime: 60 * 1000,
    gcTime: 5 * 60 * 1000,
  })

  const updatePermissions = (newPermissions: WorkspacePermissions): void => {
    if (workspaceId) {
      queryClient.setQueryData(
        [...workspacePermissionKeys.detail(workspaceId), 'my-permission'],
        newPermissions,
      )
    }
  }

  const refetch = async (): Promise<void> => {
    if (workspaceId) {
      await queryRefetch()
    }
  }

  return {
    permissions: data ?? null,
    loading: isLoading,
    error: error ? (error instanceof Error ? error.message : 'Unknown error') : null,
    updatePermissions,
    refetch,
  }
}

// ============================================================================
// Helper Hooks
// ============================================================================

/**
 * Hook: Refresh workspace permission cache
 */
export function useInvalidateWorkspacePermissions() {
  const queryClient = useQueryClient()

  return (workspaceId: string) => {
    queryClient.invalidateQueries({
      queryKey: workspacePermissionKeys.detail(workspaceId),
    })
  }
}

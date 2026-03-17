/**
 * Workspace Detail Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 *
 * Note: This file handles workspace detail/settings queries.
 * For workspace list queries, see workspaces.ts
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPatch, API_ENDPOINTS } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'

import { STALE_TIME } from './constants'

const logger = createLogger('WorkspaceDetailQueries')

/**
 * Query key factories for workspace detail-related queries
 * Note: This is for workspace detail/settings, not the workspace list.
 * For workspace list, see workspaces.ts
 */
export const workspaceDetailKeys = {
  all: ['workspace'] as const,
  details: () => [...workspaceDetailKeys.all, 'detail'] as const,
  detail: (id: string) => [...workspaceDetailKeys.details(), id] as const,
  settings: (id: string) => [...workspaceDetailKeys.detail(id), 'settings'] as const,
  permissions: (id: string) => [...workspaceDetailKeys.detail(id), 'permissions'] as const,
  adminLists: () => [...workspaceDetailKeys.all, 'adminList'] as const,
  adminList: (userId: string | undefined) => [...workspaceDetailKeys.adminLists(), userId ?? ''] as const,
}

// Note: workspaceKeys alias removed to avoid conflict with workspaces.ts
// Use workspaceDetailKeys instead for workspace detail queries

/**
 * Fetch workspace settings
 */
async function fetchWorkspaceSettings(workspaceId: string) {
  logger.info('Fetching workspace settings', { workspaceId })

  const [settingsResult, permissionsResult] = await Promise.allSettled([
    apiGet<{ workspace: any }>(`${API_ENDPOINTS.workspaces}/${workspaceId}`),
    apiGet<any>(`${API_ENDPOINTS.workspaces}/${workspaceId}/permissions`),
  ])

  const settings = settingsResult.status === 'fulfilled' ? settingsResult.value : null
  const permissions = permissionsResult.status === 'fulfilled' ? permissionsResult.value : { users: [] }

  if (!settings) {
    throw new Error('Failed to fetch workspace settings')
  }

  return {
    settings,
    permissions,
  }
}

/**
 * Hook to fetch workspace settings
 */
export function useWorkspaceSettings(workspaceId: string) {
  return useQuery({
    queryKey: workspaceDetailKeys.settings(workspaceId),
    queryFn: () => fetchWorkspaceSettings(workspaceId),
    enabled: !!workspaceId,
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

/**
 * Update workspace settings mutation
 */
interface UpdateWorkspaceSettingsParams {
  workspaceId: string
  name?: string
  allowPersonalApiKeys?: boolean
  settings?: Record<string, any>
}

export function useUpdateWorkspaceSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ workspaceId, ...updates }: UpdateWorkspaceSettingsParams) => {
      logger.info('Updating workspace settings', { workspaceId, updates })
      const result = await apiPatch<{ workspace: any }>(
        `${API_ENDPOINTS.workspaces}/${workspaceId}`,
        updates
      )
      return result
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: workspaceDetailKeys.settings(variables.workspaceId),
      })
      logger.info('Workspace settings updated', { workspaceId: variables.workspaceId })
    },
    onError: (error) => {
      logger.error('Failed to update workspace settings', { error })
    },
  })
}

/**
 * Workspace type returned by admin workspaces query
 */
export interface AdminWorkspace {
  id: string
  name: string
  isOwner: boolean
  ownerId?: string
  canInvite: boolean
}

/**
 * Fetch workspaces where user has admin access
 */
async function fetchAdminWorkspaces(userId: string | undefined): Promise<AdminWorkspace[]> {
  if (!userId) {
    return []
  }

  logger.info('Fetching admin workspaces', { userId })

  const workspacesData = await apiGet<{ workspaces: any[] }>(API_ENDPOINTS.workspaces)
  const allUserWorkspaces = workspacesData.workspaces || []

  const permissionPromises = allUserWorkspaces.map(
    async (workspace: { id: string; name: string; isOwner?: boolean; ownerId?: string }) => {
      try {
        const permissionData = await apiGet<any>(`${API_ENDPOINTS.workspaces}/${workspace.id}/permissions`)
        return { workspace, permissionData }
      } catch {
        return null
      }
    }
  )

  const results = await Promise.all(permissionPromises)

  const adminWorkspaces: AdminWorkspace[] = []
  for (const result of results) {
    if (!result) continue

    const { workspace, permissionData } = result
    let hasAdminAccess = false

    if (permissionData.users) {
      const currentUserPermission = permissionData.users.find(
        (user: { id: string; userId?: string; permissionType: string }) =>
          user.id === userId || user.userId === userId
      )
      hasAdminAccess = currentUserPermission?.permissionType === 'admin'
    }

    const isOwner = workspace.isOwner || workspace.ownerId === userId

    if (hasAdminAccess || isOwner) {
      adminWorkspaces.push({
        id: workspace.id,
        name: workspace.name,
        isOwner,
        ownerId: workspace.ownerId,
        canInvite: true,
      })
    }
  }

  logger.info('Fetched admin workspaces', { count: adminWorkspaces.length })
  return adminWorkspaces
}

/**
 * Hook to fetch workspaces where user has admin access
 */
export function useAdminWorkspaces(userId: string | undefined) {
  return useQuery({
    queryKey: workspaceDetailKeys.adminList(userId),
    queryFn: () => fetchAdminWorkspaces(userId),
    enabled: Boolean(userId),
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

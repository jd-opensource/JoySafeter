import { useMemo } from 'react'

import type { WorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useSession } from '@/lib/auth/auth-client'
import type { PermissionType } from '@/lib/workspaces/permissions/types'

export interface WorkspaceUserPermissions {
  // Core permission checks
  canRead: boolean
  canEdit: boolean
  canAdmin: boolean

  // Utility properties
  userPermissions: PermissionType
  isLoading: boolean
  error: string | null
}

/**
 * Custom hook to check current user's permissions within a workspace
 * This version accepts workspace permissions to avoid duplicate API calls
 *
 * @param workspacePermissions - The workspace permissions data
 * @param permissionsLoading - Whether permissions are currently loading
 * @param permissionsError - Any error from fetching permissions
 * @returns Object containing permission flags and utility properties
 */
export function useUserPermissions(
  workspacePermissions: WorkspacePermissions | null,
  permissionsLoading = false,
  permissionsError: string | null = null
): WorkspaceUserPermissions {
  const { data: session } = useSession()

  const userPermissions = useMemo((): WorkspaceUserPermissions => {
    const sessionEmail = session?.user?.email
    if (permissionsLoading || !sessionEmail) {
      return {
        canRead: false,
        canEdit: false,
        canAdmin: false,
        userPermissions: 'read',
        isLoading: permissionsLoading,
        error: permissionsError,
      }
    }

    const currentUser = workspacePermissions?.users?.find(
      (user) => user.email.toLowerCase() === sessionEmail.toLowerCase()
    )

    if (!currentUser) {
      return {
        canRead: false,
        canEdit: false,
        canAdmin: false,
        userPermissions: 'read',
        isLoading: false,
        error: permissionsError || 'User not found in workspace',
      }
    }

    const userPerms = currentUser.permissionType || 'read'

    const canAdmin = userPerms === 'admin'
    const canEdit = userPerms === 'write' || userPerms === 'admin'
    const canRead = true

    return {
      canRead,
      canEdit,
      canAdmin,
      userPermissions: userPerms,
      isLoading: false,
      error: permissionsError,
    }
  }, [session, workspacePermissions, permissionsLoading, permissionsError])

  return userPermissions
}

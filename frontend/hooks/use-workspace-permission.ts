'use client'

import { useMemo } from 'react'

import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import type { WorkspaceMemberRole } from '@/lib/workspaces/permissions/types'

type WorkspaceRole = WorkspaceMemberRole

export function useWorkspacePermission() {
  const { data: workspaces = [], isLoading: workspacesLoading } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')

  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(
    personalWorkspace?.id ?? null,
  )

  return useMemo(() => {
    const isLoading = workspacesLoading || permissionsLoading

    // Derive role from the API response; fall back to viewer while loading or unauthenticated
    const currentUser = permissions?.users?.[0] ?? null
    const role: WorkspaceRole = (currentUser?.role as WorkspaceRole) ?? 'viewer'

    return {
      role,
      isLoading,
      canView: true,
      canOperate: role !== 'viewer',
      canManage: role === 'admin' || role === 'owner',
      canOwn: role === 'owner',
    }
  }, [workspacesLoading, permissionsLoading, permissions])
}

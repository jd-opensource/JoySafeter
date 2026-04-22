'use client'

import { useMemo } from 'react'

import { useWorkspaces } from '@/hooks/queries/workspaces'

type WorkspaceRole = 'viewer' | 'member' | 'admin' | 'owner'

export function useWorkspacePermission() {
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')

  // For now, if user has a workspace, they're the owner
  // TODO: implement proper role checking from workspace membership
  const role: WorkspaceRole = personalWorkspace ? ('owner' as const) : ('viewer' as const)

  return useMemo(() => ({
    role,
    canView: true,
    canOperate: role !== 'viewer',
    canManage: (role as WorkspaceRole) === 'admin' || role === 'owner',
    canOwn: role === 'owner',
  }), [role])
}

'use client'

import { createContext, useContext, useEffect, useMemo } from 'react'

import { useWorkspaces, type Workspace } from '@/hooks/queries/workspaces'
import { useWorkspaceStore } from '@/stores/workspace/store'

import { WorkspacePermissionsProvider } from './workspace-permissions-provider'

interface WorkspaceContextType {
  workspaceId: string
  workspace: Workspace | null
  workspaces: Workspace[]
  switchWorkspace: (id: string) => void
  isLoading: boolean
}

const WorkspaceContext = createContext<WorkspaceContextType | null>(null)

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { data: workspaces = [], isLoading } = useWorkspaces()
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const setCurrentWorkspaceId = useWorkspaceStore((s) => s.setCurrentWorkspaceId)

  const resolvedWorkspaceId = useMemo(() => {
    if (workspaces.length === 0) return ''
    const persisted = workspaces.find((w) => w.id === currentWorkspaceId)
    if (persisted) return persisted.id
    const personal = workspaces.find((w) => w.type === 'personal')
    return personal?.id ?? workspaces[0]?.id ?? ''
  }, [workspaces, currentWorkspaceId])

  useEffect(() => {
    if (resolvedWorkspaceId && resolvedWorkspaceId !== currentWorkspaceId) {
      setCurrentWorkspaceId(resolvedWorkspaceId)
    }
  }, [resolvedWorkspaceId, currentWorkspaceId, setCurrentWorkspaceId])

  const workspace = useMemo(
    () => workspaces.find((w) => w.id === resolvedWorkspaceId) ?? null,
    [workspaces, resolvedWorkspaceId],
  )

  const value = useMemo<WorkspaceContextType>(
    () => ({
      workspaceId: resolvedWorkspaceId,
      workspace,
      workspaces,
      switchWorkspace: setCurrentWorkspaceId,
      isLoading,
    }),
    [resolvedWorkspaceId, workspace, workspaces, setCurrentWorkspaceId, isLoading],
  )

  return (
    <WorkspaceContext.Provider value={value}>
      <WorkspacePermissionsProvider workspaceId={resolvedWorkspaceId}>
        {children}
      </WorkspacePermissionsProvider>
    </WorkspaceContext.Provider>
  )
}

export function useCurrentWorkspace(): WorkspaceContextType {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) {
    throw new Error('useCurrentWorkspace must be used within a WorkspaceProvider')
  }
  return ctx
}

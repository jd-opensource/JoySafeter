'use client'

import { createContext, useContext, useMemo } from 'react'

import { useSession } from '@/lib/auth/auth-client'
import { canAdmin, canOwn, canRead, canWrite, normalizeManagedRole } from '@/lib/managed/roles'
import { useProjectStore } from '@/stores/managed/project-store'

export interface UserPermissions {
  canRead: boolean
  canEdit: boolean
  canAdmin: boolean
  isOwner: boolean
  role: string | null
  userPermissions: string
  isLoading: boolean
  error: string | null
  isOfflineMode?: boolean
}

const defaultPermissions: UserPermissions = {
  canRead: true,
  canEdit: true,
  canAdmin: false,
  isOwner: false,
  role: 'developer',
  userPermissions: 'write',
  isLoading: false,
  error: null,
}

const PermissionsContext = createContext<UserPermissions>(defaultPermissions)

export function PermissionsProvider({ children }: { children: React.ReactNode }) {
  const { data: session, isPending } = useSession()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const organizations = useProjectStore((state) => state.organizations)

  const permissions = useMemo<UserPermissions>(() => {
    if (isPending) {
      return { ...defaultPermissions, isLoading: true, canRead: false, canEdit: false }
    }
    if (!session?.user) {
      return { ...defaultPermissions, canRead: false, canEdit: false, role: null }
    }
    const currentOrg = organizations.find((org) => org.id === currentOrgId)
    const role = normalizeManagedRole(currentOrg?.role || null)
    return {
      canRead: canRead(role),
      canEdit: canWrite(role),
      canAdmin: canAdmin(role),
      isOwner: canOwn(role),
      role,
      userPermissions: canWrite(role) ? 'write' : 'read',
      isLoading: false,
      error: null,
    }
  }, [session, isPending, organizations, currentOrgId])

  return (
    <PermissionsContext.Provider value={permissions}>
      {children}
    </PermissionsContext.Provider>
  )
}

export function useUserPermissionsContext(): UserPermissions {
  return useContext(PermissionsContext)
}

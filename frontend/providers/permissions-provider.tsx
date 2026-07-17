'use client'

import { createContext, useContext, useMemo } from 'react'

import { useSession } from '@/lib/auth/auth-client'
import { canAdmin, canOwn, canRead, normalizeManagedRole } from '@/lib/managed/roles'
import { useProjectStore } from '@/stores/managed/project-store'

export interface UserPermissions {
  canRead: boolean
  canAdmin: boolean
  isOwner: boolean
  role: string | null
  isLoading: boolean
  error: string | null
  isOfflineMode?: boolean
}

const defaultPermissions: UserPermissions = {
  canRead: true,
  canAdmin: false,
  isOwner: false,
  role: 'member',
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
      return { ...defaultPermissions, isLoading: true, canRead: false }
    }
    if (!session?.user) {
      return { ...defaultPermissions, canRead: false, role: null }
    }
    const currentOrg = organizations.find((org) => org.id === currentOrgId)
    const role = normalizeManagedRole(currentOrg?.role || null)
    return {
      canRead: canRead(role),
      canAdmin: canAdmin(role),
      isOwner: canOwn(role),
      role,
      isLoading: false,
      error: null,
    }
  }, [session, isPending, organizations, currentOrgId])

  return <PermissionsContext.Provider value={permissions}>{children}</PermissionsContext.Provider>
}

export function useUserPermissionsContext(): UserPermissions {
  return useContext(PermissionsContext)
}

'use client'

import { createContext, useContext, useMemo } from 'react'

import { useProjectContext } from '@/hooks/managed/use-project-context'
import type { OrgInfo, ProjectInfo } from '@/stores/managed/project-store'

interface OrganizationContextType {
  organizationId: string
  organizationName: string
  organizations: OrgInfo[]
  projectId: string
  projectName: string
  projects: ProjectInfo[]
  switchProject: (id: string) => void
  isLoading: boolean
}

const OrganizationContext = createContext<OrganizationContextType | null>(null)

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const { orgId, projectId, organizations, projects, isLoading, switchProject } =
    useProjectContext()

  const currentOrg = useMemo(
    () => organizations.find((o) => o.id === orgId),
    [organizations, orgId],
  )

  const currentProject = useMemo(
    () => projects.find((p) => p.id === projectId),
    [projects, projectId],
  )

  const value = useMemo<OrganizationContextType>(
    () => ({
      organizationId: orgId || '',
      organizationName: currentOrg?.name || '',
      organizations,
      projectId: projectId || '',
      projectName: currentProject?.name || '',
      projects,
      switchProject,
      isLoading,
    }),
    [orgId, currentOrg, organizations, projectId, currentProject, projects, switchProject, isLoading],
  )

  return (
    <OrganizationContext.Provider value={value}>
      {children}
    </OrganizationContext.Provider>
  )
}

export function useCurrentOrganization(): OrganizationContextType {
  const ctx = useContext(OrganizationContext)
  if (!ctx) {
    throw new Error('useCurrentOrganization must be used within an OrganizationProvider')
  }
  return ctx
}

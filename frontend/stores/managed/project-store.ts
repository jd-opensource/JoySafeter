import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface OrgInfo {
  id: string
  name: string
  slug: string
  role: string
}

export interface ProjectInfo {
  id: string
  org_id?: string
  name: string
  slug: string
  is_default: boolean
}

interface ProjectState {
  currentOrgId: string | null
  currentProjectId: string | null
  organizations: OrgInfo[]
  projects: ProjectInfo[]
  setCurrentOrg: (orgId: string) => void
  setCurrentProject: (projectId: string) => void
  setContext: (orgId: string, projectId: string, orgs: OrgInfo[], projects: ProjectInfo[]) => void
  clearContext: () => void
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
      setCurrentOrg: (orgId) => set({ currentOrgId: orgId }),
      setCurrentProject: (projectId) => set({ currentProjectId: projectId }),
      setContext: (orgId, projectId, orgs, projects) =>
        set({
          currentOrgId: orgId,
          currentProjectId: projectId,
          organizations: orgs,
          projects,
        }),
      clearContext: () =>
        set({
          currentOrgId: null,
          currentProjectId: null,
          organizations: [],
          projects: [],
        }),
    }),
    {
      name: 'managed-project-state',
    },
  ),
)

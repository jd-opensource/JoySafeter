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
    }),
    {
      name: 'managed-project-state',
    },
  ),
)

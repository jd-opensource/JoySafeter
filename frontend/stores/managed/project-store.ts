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
  archived_at?: string | null
}

interface ProjectState {
  currentOrgId: string | null
  currentProjectId: string | null
  currentProject: ProjectInfo | null
  organizations: OrgInfo[]
  projects: ProjectInfo[]
  setCurrentOrg: (orgId: string) => void
  setCurrentProject: (projectId: string) => void
  setContext: (
    orgId: string,
    projectId: string,
    orgs: OrgInfo[],
    projects: ProjectInfo[],
    currentProject?: ProjectInfo | null,
  ) => void
  clearContext: () => void
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      currentOrgId: null,
      currentProjectId: null,
      currentProject: null,
      organizations: [],
      projects: [],
      setCurrentOrg: (orgId) =>
        set((state) => {
          if (state.currentOrgId === orgId) {
            return { currentOrgId: orgId }
          }
          return {
            currentOrgId: orgId,
            currentProjectId: null,
            currentProject: null,
            projects: [],
          }
        }),
      setCurrentProject: (projectId) =>
        set((state) => ({
          currentProjectId: projectId,
          currentProject: state.projects.find((project) => project.id === projectId) || null,
        })),
      setContext: (orgId, projectId, orgs, projects, currentProject) =>
        set({
          currentOrgId: orgId,
          currentProjectId: projectId,
          currentProject:
            currentProject && currentProject.id === projectId
              ? currentProject
              : projects.find((project) => project.id === projectId) || null,
          organizations: orgs,
          projects,
        }),
      clearContext: () =>
        set({
          currentOrgId: null,
          currentProjectId: null,
          currentProject: null,
          organizations: [],
          projects: [],
        }),
    }),
    {
      name: 'managed-project-state',
    },
  ),
)

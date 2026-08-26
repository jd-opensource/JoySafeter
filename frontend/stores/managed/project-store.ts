import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { parseOrganizationId, parseProjectId } from '@/types/entity-id'

export interface OrgInfo {
  id: string
  name: string
  slug: string
  role: string
  owner_name?: string | null
  owner_email?: string | null
  project_creation_policy?: 'admins_only' | 'all_members'
}

export interface ProjectInfo {
  id: string
  org_id?: string
  name: string
  slug: string
  is_default: boolean
  archived_at?: string | null
  // Present on the active project returned by /auth/me and switch-context.
  capability?: string
  project_role?: string | null
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

function parsePersistedContext(
  value: unknown,
): Pick<ProjectState, 'currentOrgId' | 'currentProjectId'> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { currentOrgId: null, currentProjectId: null }
  }

  const stored = value as Record<string, unknown>
  let currentOrgId: string | null = null
  if (stored.currentOrgId !== undefined && stored.currentOrgId !== null) {
    if (typeof stored.currentOrgId !== 'string') {
      return { currentOrgId: null, currentProjectId: null }
    }
    try {
      currentOrgId = parseOrganizationId(stored.currentOrgId)
    } catch {
      return { currentOrgId: null, currentProjectId: null }
    }
  }

  if (currentOrgId === null) {
    return { currentOrgId: null, currentProjectId: null }
  }

  if (stored.currentProjectId === undefined || stored.currentProjectId === null) {
    return { currentOrgId, currentProjectId: null }
  }
  if (typeof stored.currentProjectId !== 'string') {
    return { currentOrgId, currentProjectId: null }
  }

  try {
    return { currentOrgId, currentProjectId: parseProjectId(stored.currentProjectId) }
  } catch {
    return { currentOrgId, currentProjectId: null }
  }
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
      version: 1,
      migrate: (persistedState) => parsePersistedContext(persistedState),
      merge: (persistedState, currentState) => ({
        ...currentState,
        ...parsePersistedContext(persistedState),
      }),
      partialize: (state) => ({
        currentOrgId: state.currentOrgId,
        currentProjectId: state.currentProjectId,
      }),
    },
  ),
)

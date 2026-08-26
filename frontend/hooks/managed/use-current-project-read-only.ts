import { useProjectStore } from '@/stores/managed/project-store'
import type { ProjectInfo } from '@/stores/managed/project-store'
import type { ProjectId } from '@/types/entity-id'

function isReadOnly(projectId: ProjectId | null, project: ProjectInfo | null): boolean {
  if (!projectId) return false
  if (!project || project.archived_at) return true
  return project.capability !== 'write' && project.capability !== 'admin'
}

export function useCurrentProjectReadOnly(): boolean {
  return useProjectStore((state) => isReadOnly(state.currentProjectId, state.currentProject))
}

export function currentProjectAllowsWrite(): boolean {
  const { currentProjectId, currentProject } = useProjectStore.getState()
  return Boolean(currentProjectId) && !isReadOnly(currentProjectId, currentProject)
}

// ADMIN-tier gate for privileged skill actions (lifecycle transitions,
// publish, delete) whose backend requires ProjectCapability.ADMIN.
function isAdmin(projectId: ProjectId | null, project: ProjectInfo | null): boolean {
  if (!projectId) return false
  if (!project || project.archived_at) return false
  return project.capability === 'admin'
}

export function useCurrentProjectIsAdmin(): boolean {
  return useProjectStore((state) => isAdmin(state.currentProjectId, state.currentProject))
}

export function currentProjectAllowsAdmin(): boolean {
  const { currentProjectId, currentProject } = useProjectStore.getState()
  return isAdmin(currentProjectId, currentProject)
}

import { useProjectStore } from '@/stores/managed/project-store'
import type { ProjectInfo } from '@/stores/managed/project-store'

// capability is absent on legacy/persisted state or projects-list entries — in
// that case we do NOT restrict (backward-safe; capability repopulates on the
// next /auth/me). We only mark read-only when the capability is known and below
// write, or the project is archived/missing.
function isReadOnly(projectId: string | null, project: ProjectInfo | null): boolean {
  if (!projectId) return false
  if (!project || project.archived_at) return true
  return project.capability === 'read' || project.capability === 'none'
}

export function useCurrentProjectReadOnly(): boolean {
  return useProjectStore((state) => isReadOnly(state.currentProjectId, state.currentProject))
}

export function currentProjectAllowsWrite(): boolean {
  const { currentProjectId, currentProject } = useProjectStore.getState()
  return Boolean(currentProjectId) && !isReadOnly(currentProjectId, currentProject)
}

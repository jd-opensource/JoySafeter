import { useProjectStore } from '@/stores/managed/project-store'

export function useCurrentProjectReadOnly(): boolean {
  return useProjectStore((state) =>
    Boolean(state.currentProjectId && (!state.currentProject || state.currentProject.archived_at)),
  )
}

export function currentProjectAllowsWrite(): boolean {
  const { currentProjectId, currentProject } = useProjectStore.getState()
  return Boolean(currentProjectId && currentProject && !currentProject.archived_at)
}

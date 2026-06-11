'use client'

import { useEffect, useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrgInfo, ProjectInfo } from '@/stores/managed/project-store'

interface AuthMeResponse {
  user: {
    id: string
    email: string
    name: string
  }
  organization: OrgInfo
  project: ProjectInfo
  organizations: OrgInfo[]
  projects: ProjectInfo[]
}

interface SwitchContextResponse {
  project: ProjectInfo
  projects: ProjectInfo[]
}

export function useProjectContext() {
  const [isLoading, setIsLoading] = useState(true)
  const queryClient = useQueryClient()
  const { currentOrgId, currentProjectId, organizations, projects, setContext, setCurrentProject } =
    useProjectStore()

  useEffect(() => {
    let cancelled = false

    const loadContext = async () => {
      try {
        const data = await managedGet<AuthMeResponse>('/auth/me', { skipManagedContext: true })
        if (cancelled) return

        setContext(
          data.organization.id,
          data.project.id,
          data.organizations,
          data.projects,
        )
      } catch (err) {
        console.error('Failed to load project context:', err)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    loadContext()

    return () => {
      cancelled = true
    }
  }, [setContext])

  const switchProject = useCallback(
    async (projectId: string) => {
      try {
        const data = await managedPost<SwitchContextResponse>('/auth/switch-context', {
          project_id: projectId,
        })
        setCurrentProject(data.project.id)
        queryClient.invalidateQueries()
      } catch (err) {
        console.error('Failed to switch project:', err)
      }
    },
    [setCurrentProject, queryClient],
  )

  return {
    orgId: currentOrgId || '',
    projectId: currentProjectId || '',
    organizations,
    projects,
    isLoading,
    switchProject,
  }
}

'use client'

import { useEffect, useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError, managedGet, managedPost } from '@/lib/api-client'
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
  org_id?: string
  project: ProjectInfo
  projects: ProjectInfo[]
}

async function loadAuthContext(): Promise<AuthMeResponse> {
  try {
    return await managedGet<AuthMeResponse>('/auth/me')
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      return managedGet<AuthMeResponse>('/auth/me', { skipManagedContext: true })
    }
    throw error
  }
}

export function useProjectContext() {
  const [isLoading, setIsLoading] = useState(true)
  const queryClient = useQueryClient()
  const { currentOrgId, currentProjectId, organizations, projects, setContext } = useProjectStore()

  useEffect(() => {
    let cancelled = false

    const loadContext = async () => {
      try {
        const data = await loadAuthContext()
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
    async (projectId: string, orgId?: string) => {
      try {
        const data = await managedPost<SwitchContextResponse>('/auth/switch-context', {
          org_id: orgId,
          project_id: projectId,
        }, {
          skipManagedContext: true,
          headers: orgId ? { 'X-Org-Id': orgId } : undefined,
        })
        setContext(data.org_id || orgId || currentOrgId || '', data.project.id, organizations, data.projects)
        queryClient.invalidateQueries()
      } catch (err) {
        console.error('Failed to switch project:', err)
        throw err
      }
    },
    [currentOrgId, organizations, setContext, queryClient],
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

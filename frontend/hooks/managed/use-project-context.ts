'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, useCallback } from 'react'

import { managedGet, managedPost } from '@/lib/api-client'
import { parseApiError } from '@/lib/managed/errors'
import { clearNonSessionQueryData } from '@/lib/query-client-lifecycle'
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
    const { code } = parseApiError(error)
    if (
      code === 'JOYSAFETER_UNAUTHORIZED' ||
      code === 'UNAUTHORIZED' ||
      code === 'PROJECT_ACCESS_DENIED' ||
      code === 'NOT_ORG_MEMBER' ||
      code === 'MEMBERSHIP_EXPIRED' ||
      code === 'HTTP_401' ||
      code === 'HTTP_403'
    ) {
      return managedGet<AuthMeResponse>('/auth/me', { skipManagedContext: true })
    }
    throw error
  }
}

export function useProjectContext() {
  const [isLoading, setIsLoading] = useState(true)
  const queryClient = useQueryClient()
  const contextLoadSeqRef = useRef(0)
  const switchRequestSeqRef = useRef(0)
  const { currentOrgId, currentProjectId, organizations, projects, setContext } = useProjectStore()

  useEffect(() => {
    let cancelled = false
    const loadSeq = contextLoadSeqRef.current

    const loadContext = async () => {
      try {
        const data = await loadAuthContext()
        if (cancelled || loadSeq !== contextLoadSeqRef.current) return

        setContext(data.organization.id, data.project.id, data.organizations, data.projects)
      } catch (err) {
        if (loadSeq === contextLoadSeqRef.current) {
          console.error('Failed to load project context:', err)
        }
      } finally {
        if (!cancelled && loadSeq === contextLoadSeqRef.current) setIsLoading(false)
      }
    }

    loadContext()

    return () => {
      cancelled = true
    }
  }, [setContext])

  const switchProject = useCallback(
    async (projectId: string, orgId?: string) => {
      const requestSeq = (switchRequestSeqRef.current += 1)
      try {
        const data = await managedPost<SwitchContextResponse>(
          '/auth/switch-context',
          {
            org_id: orgId,
            project_id: projectId,
          },
          {
            skipManagedContext: true,
            headers: orgId ? { 'X-Org-Id': orgId } : undefined,
          },
        )
        if (requestSeq !== switchRequestSeqRef.current) return
        contextLoadSeqRef.current += 1
        setContext(
          data.org_id || orgId || currentOrgId || '',
          data.project.id,
          organizations,
          data.projects,
        )
        setIsLoading(false)
        clearNonSessionQueryData(queryClient)
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

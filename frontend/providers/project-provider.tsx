'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { ApiError, managedGet } from '@/lib/api-client'
import { useSession } from '@/lib/auth/auth-client'
import {
  parseAuthContextResponse,
  type AuthContextResponse,
  type AuthContextResponsePayload,
} from '@/lib/managed/tenant-response-parsers'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrganizationId, ProjectId } from '@/types/entity-id'

interface AuthMeQueryResult {
  data: AuthContextResponse
  requestedOrgId: OrganizationId | null
  requestedProjectId: ProjectId | null
}

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession()
  const setContext = useProjectStore((s) => s.setContext)
  const clearContext = useProjectStore((s) => s.clearContext)
  const currentOrgId = useProjectStore((s) => s.currentOrgId)
  const currentProjectId = useProjectStore((s) => s.currentProjectId)
  const sessionUserId = session?.user?.id ?? null

  const { data: authMeResult, isLoading } = useQuery<AuthMeQueryResult>({
    queryKey: ['auth-me', sessionUserId],
    queryFn: async () => {
      const { currentOrgId: requestedOrgId, currentProjectId: requestedProjectId } =
        useProjectStore.getState()
      let payload: AuthContextResponsePayload
      try {
        payload = await managedGet<AuthContextResponsePayload>('/auth/me')
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          payload = await managedGet<AuthContextResponsePayload>('/auth/me', {
            skipManagedContext: true,
          })
        } else {
          throw error
        }
      }
      return { data: parseAuthContextResponse(payload), requestedOrgId, requestedProjectId }
    },
    enabled: !!sessionUserId,
    staleTime: 30_000,
  })

  useEffect(() => {
    if (sessionUserId) return
    clearContext()
  }, [clearContext, sessionUserId])

  useEffect(() => {
    if (authMeResult) {
      const requestStartedWithoutContext =
        authMeResult.requestedOrgId === null && authMeResult.requestedProjectId === null
      const contextChangedSinceRequest = requestStartedWithoutContext
        ? currentOrgId !== null || currentProjectId !== null
        : authMeResult.requestedOrgId !== currentOrgId ||
          authMeResult.requestedProjectId !== currentProjectId

      if (contextChangedSinceRequest) return

      const { data } = authMeResult
      setContext(
        data.organization.id,
        data.project.id,
        data.organizations,
        data.projects,
        data.project,
      )
    }
  }, [authMeResult, currentOrgId, currentProjectId, setContext])

  if (!session?.user) return <>{children}</>
  if (isLoading || !authMeResult) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-primary" />
      </div>
    )
  }

  return <>{children}</>
}

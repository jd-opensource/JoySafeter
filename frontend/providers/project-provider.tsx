'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { ApiError, managedGet } from '@/lib/api-client'
import { useSession } from '@/lib/auth/auth-client'
import { useProjectStore } from '@/stores/managed/project-store'

interface AuthMeResponse {
  organization: { id: string; name: string; slug: string; role: string }
  project: {
    id: string
    name: string
    slug: string
    is_default: boolean
    archived_at?: string | null
    capability: string
    project_role?: string | null
  }
  organizations: Array<{ id: string; name: string; slug: string; role: string }>
  projects: Array<{
    id: string
    name: string
    slug: string
    is_default: boolean
    archived_at?: string | null
  }>
}

interface AuthMeQueryResult {
  data: AuthMeResponse
  requestedOrgId: string | null
  requestedProjectId: string | null
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
      let data: AuthMeResponse
      try {
        data = await managedGet<AuthMeResponse>('/auth/me')
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          data = await managedGet<AuthMeResponse>('/auth/me', { skipManagedContext: true })
        } else {
          throw error
        }
      }
      return { data, requestedOrgId, requestedProjectId }
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

'use client'

import { managedGet } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import { useSession } from '@/lib/auth/auth-client'
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

interface AuthMeResponse {
  organization: { id: string; name: string; slug: string; role: string }
  project: { id: string; name: string; slug: string; is_default: boolean }
  organizations: Array<{ id: string; name: string; slug: string; role: string }>
  projects: Array<{ id: string; name: string; slug: string; is_default: boolean }>
}

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession()
  const setContext = useProjectStore((s) => s.setContext)

  const { data, isLoading } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => managedGet<AuthMeResponse>('/auth/me', { skipManagedContext: true }),
    enabled: !!session?.user,
    staleTime: 30_000,
  })

  useEffect(() => {
    if (data) {
      setContext(data.organization.id, data.project.id, data.organizations, data.projects)
    }
  }, [data, setContext])

  if (!session?.user) return <>{children}</>
  if (isLoading || !data) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-primary" />
      </div>
    )
  }

  return <>{children}</>
}

'use client'

import { useQuery } from '@tanstack/react-query'
import { FolderCode } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const projectTabs = [
  { segment: '', labelKey: 'managed.projectSettings.tabs.overview', requiresAdmin: false },
  { segment: 'access', labelKey: 'managed.projectSettings.tabs.access', requiresAdmin: true },
  { segment: 'tokens', labelKey: 'managed.projectSettings.tabs.tokens', requiresAdmin: true },
  { segment: 'lifecycle', labelKey: 'managed.projectSettings.tabs.lifecycle', requiresAdmin: true },
]

interface ProjectSettingsSummary {
  id: string
  org_id: string
  name: string
  slug: string
  is_default: boolean
  archived_at?: string | null
  capability?: string
}

export function ProjectSettingsShell({
  projectId,
  children,
}: {
  projectId: string
  children: ReactNode
}) {
  const pathname = usePathname()
  const { t } = useTranslation()
  const { orgId, organizations, isLoading: contextLoading } = useProjectContext()
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => managedGet<ProjectSettingsSummary>(`auth/projects/${projectId}`),
    enabled: Boolean(projectId),
  })
  const project = projectQuery.data ?? null
  const organization = organizations.find((org) => org.id === (project?.org_id || orgId))

  if (contextLoading || projectQuery.isLoading) {
    return (
      <div className="flex w-full flex-col gap-5" aria-label={t('managed.projectSettings.loading')}>
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-9 w-96 max-w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 text-center">
        <h2 className="text-lg font-semibold text-foreground">
          {t('managed.projectSettings.notFoundTitle')}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t('managed.projectSettings.notFoundDescription')}
        </p>
        <Link href="/managed/projects" className="text-sm text-primary hover:underline">
          {t('managed.projectSettings.backToProjects')}
        </Link>
      </div>
    )
  }

  const basePath = `/managed/projects/${projectId}`
  const canManageProject = project.capability === 'admin'
  const visibleTabs = projectTabs.filter((tab) => canManageProject || !tab.requiresAdmin)
  const routeSegment = pathname.startsWith(`${basePath}/`)
    ? pathname.slice(basePath.length + 1).split('/')[0]
    : ''
  const restrictedRoute =
    !canManageProject &&
    projectTabs.some((tab) => tab.requiresAdmin && tab.segment === routeSegment)

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-col gap-3">
        <Link
          href="/managed/projects"
          className="w-fit text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          {t('managed.projectSettings.backToProjects')}
        </Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
              <FolderCode className="size-5 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm text-muted-foreground">{organization?.name}</p>
              <h1 className="truncate text-2xl font-semibold text-foreground">{project?.name}</h1>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">
              {t(`managed.projectSettings.capability.${project?.capability || 'read'}`)}
            </Badge>
            {project?.is_default ? (
              <Badge variant="outline">{t('managed.projectSettings.default')}</Badge>
            ) : null}
            {project?.archived_at ? (
              <Badge variant="outline">{t('managed.projectSettings.archived')}</Badge>
            ) : null}
          </div>
        </div>
      </header>

      <nav aria-label={t('managed.projectSettings.tabs.label')} className="border-b border-border">
        <div className="flex gap-6 overflow-x-auto">
          {visibleTabs.map((tab) => {
            const href = tab.segment ? `${basePath}/${tab.segment}` : basePath
            const active = pathname === href
            return (
              <Link
                key={tab.segment || 'overview'}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'border-b-2 border-transparent px-1 pb-3 pt-1 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground',
                  active && 'border-primary text-foreground',
                )}
              >
                {t(tab.labelKey)}
              </Link>
            )
          })}
        </div>
      </nav>

      {restrictedRoute ? (
        <div className="rounded-lg border border-border bg-muted/30 p-6">
          <h2 className="text-lg font-semibold text-foreground">
            {t('managed.projectSettings.restricted.title')}
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {t('managed.projectSettings.restricted.description')}
          </p>
          <Link
            href={basePath}
            className="mt-4 inline-flex text-sm font-medium text-primary hover:underline"
          >
            {t('managed.projectSettings.restricted.backToOverview')}
          </Link>
        </div>
      ) : (
        children
      )}
    </div>
  )
}

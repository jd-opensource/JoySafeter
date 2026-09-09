'use client'

import { useQuery } from '@tanstack/react-query'
import { FolderCode } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { PageHeader, TabNav } from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import { useTranslation } from '@/lib/i18n'
import { fetchManagedProject, managedProjectQueryKey } from '@/lib/managed/project-client'
import { useManagedRequestScope } from '@/lib/managed/request-scope'
import type { OrganizationId, ProjectId } from '@/types/entity-id'

const projectTabs = [
  { segment: '', labelKey: 'managed.projectSettings.tabs.overview', requiresAdmin: false },
  { segment: 'access', labelKey: 'managed.projectSettings.tabs.access', requiresAdmin: true },
  { segment: 'tokens', labelKey: 'managed.projectSettings.tabs.tokens', requiresAdmin: true },
  { segment: 'lifecycle', labelKey: 'managed.projectSettings.tabs.lifecycle', requiresAdmin: true },
]

export function ProjectSettingsShell({
  projectId,
  children,
}: {
  projectId: ProjectId
  children: ReactNode
}) {
  const pathname = usePathname()
  const { t } = useTranslation()
  const { orgId, organizations, isLoading: contextLoading } = useProjectContext()
  const requestScope = useManagedRequestScope()
  const projectQuery = useQuery({
    queryKey: managedProjectQueryKey(requestScope.orgId, projectId),
    queryFn: () => fetchManagedProject(projectId, requestScope),
    enabled: Boolean(projectId),
  })
  const project = projectQuery.data ?? null
  const organizationId: OrganizationId | null = project?.org_id ?? orgId
  const organization = organizations.find((org) => org.id === organizationId)

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
    <div>
      <PageHeader
        title={project.name}
        icon={<FolderCode />}
        breadcrumb={[
          { label: t('manage.projects.title'), to: '/managed/projects' },
          { label: project.name },
        ]}
        titleExtra={
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">
              {t(`managed.projectSettings.capability.${project.capability || 'read'}`)}
            </Badge>
            {project.is_default ? (
              <Badge variant="outline">{t('managed.projectSettings.default')}</Badge>
            ) : null}
            {project.archived_at ? (
              <Badge variant="outline">{t('managed.projectSettings.archived')}</Badge>
            ) : null}
          </div>
        }
        subtitle={organization?.name}
      />

      <TabNav
        label={t('managed.projectSettings.tabs.label')}
        items={visibleTabs.map((tab) => ({
          href: tab.segment ? `${basePath}/${tab.segment}` : basePath,
          label: t(tab.labelKey),
        }))}
      />

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

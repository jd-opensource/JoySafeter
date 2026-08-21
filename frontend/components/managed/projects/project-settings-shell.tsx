'use client'

import { FolderCode } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useProjectStore } from '@/stores/managed/project-store'

const projectTabs = [
  { segment: '', labelKey: 'managed.projectSettings.tabs.overview' },
  { segment: 'access', labelKey: 'managed.projectSettings.tabs.access' },
  { segment: 'tokens', labelKey: 'managed.projectSettings.tabs.tokens' },
  { segment: 'lifecycle', labelKey: 'managed.projectSettings.tabs.lifecycle' },
]

export function ProjectSettingsShell({
  projectId,
  children,
}: {
  projectId: string
  children: ReactNode
}) {
  const pathname = usePathname()
  const { t } = useTranslation()
  const {
    orgId,
    projectId: activeProjectId,
    organizations,
    projects,
    isLoading,
    switchProject,
  } = useProjectContext()
  const storedCurrentProject = useProjectStore((state) => state.currentProject)
  const switchingProjectIdRef = useRef<string | null>(null)
  const [switchError, setSwitchError] = useState<unknown>(null)
  const targetProject = projects.find((project) => project.id === projectId) ?? null
  const project =
    activeProjectId === projectId && storedCurrentProject?.id === projectId
      ? storedCurrentProject
      : targetProject
  const targetOrgId = targetProject?.org_id || orgId || undefined
  const organization = organizations.find((org) => org.id === (project?.org_id || orgId))
  const contextReady = activeProjectId === projectId && Boolean(project)

  const requestContextSwitch = useCallback(() => {
    if (!projectId || switchingProjectIdRef.current === projectId) return
    switchingProjectIdRef.current = projectId
    void switchProject(projectId, targetOrgId)
      .catch((error) => setSwitchError(error))
      .finally(() => {
        if (switchingProjectIdRef.current === projectId) switchingProjectIdRef.current = null
      })
  }, [projectId, switchProject, targetOrgId])

  useEffect(() => {
    if (contextReady || isLoading) return
    requestContextSwitch()
  }, [contextReady, isLoading, requestContextSwitch])

  if (!contextReady) {
    if (switchError) {
      return (
        <div className="flex min-h-[360px] flex-col items-center justify-center gap-4 text-center">
          <div>
            <h2 className="text-lg font-semibold text-foreground">
              {t('managed.projectSettings.switchFailedTitle')}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('managed.projectSettings.switchFailedDescription')}
            </p>
          </div>
          <Button
            onClick={() => {
              setSwitchError(null)
              requestContextSwitch()
            }}
          >
            {t('common.retry')}
          </Button>
        </div>
      )
    }
    return (
      <div className="flex w-full flex-col gap-5" aria-label={t('managed.projectSettings.loading')}>
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-9 w-96 max-w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const basePath = `/managed/projects/${projectId}`

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
          {projectTabs.map((tab) => {
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

      {children}
    </div>
  )
}

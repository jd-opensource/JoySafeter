'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { managedGet, managedPatch } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { useUserPermissionsContext } from '@/providers/permissions-provider'
import { useProjectStore } from '@/stores/managed/project-store'

interface ProjectDetails {
  id: string
  org_id: string
  name: string
  slug: string
  is_default: boolean
  triggers_paused?: boolean
  archived_at?: string | null
  capability?: string
  project_role?: string | null
}

export function ProjectOverviewPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => managedGet<ProjectDetails>(`auth/projects/${projectId}`),
  })

  if (projectQuery.isLoading) {
    return <Skeleton className="h-72 w-full" />
  }

  if (!projectQuery.data) {
    return <p className="text-sm text-muted-foreground">{t('common.noData')}</p>
  }

  const project = projectQuery.data
  return (
    <ProjectOverviewForm
      key={`${project.id}:${project.name}:${project.slug}:${project.archived_at || ''}`}
      project={project}
    />
  )
}

function ProjectOverviewForm({ project }: { project: ProjectDetails }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { canAdmin } = useUserPermissionsContext()
  const [name, setName] = useState(project.name)
  const [slug, setSlug] = useState(project.slug)
  const archived = Boolean(project.archived_at)
  const canEditName = project.capability === 'admin' && !archived
  const canEditSlug = canAdmin && !archived
  const nameChanged = canEditName && name.trim() !== project.name
  const slugChanged = canEditSlug && slug.trim() !== project.slug
  const dirty = nameChanged || slugChanged
  const readOnly = !canEditName && !canEditSlug

  const saveProject = useMutation({
    mutationFn: () => {
      const payload: { name?: string; slug?: string } = {}
      if (nameChanged) payload.name = name.trim()
      if (slugChanged) payload.slug = slug.trim()
      return managedPatch<ProjectDetails>(`/auth/projects/${project.id}`, payload)
    },
    onSuccess: (updatedProject) => {
      queryClient.setQueryData(['project', project.id], updatedProject)
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      useProjectStore.setState((state) => ({
        currentProject:
          state.currentProjectId === updatedProject.id ? updatedProject : state.currentProject,
        projects: state.projects.map((item) =>
          item.id === updatedProject.id ? updatedProject : item,
        ),
      }))
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('managed.projectSettings.overview.title')}</CardTitle>
        <CardDescription>{t('managed.projectSettings.overview.description')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <label className="flex flex-col gap-2 text-sm font-medium text-foreground">
          {t('manage.projects.projectName')}
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={!canEditName}
          />
        </label>
        <label className="flex flex-col gap-2 text-sm font-medium text-foreground">
          {t('manage.projects.slug')}
          <Input
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            disabled={!canEditSlug}
            className="font-mono"
          />
          <span className="text-xs font-normal text-muted-foreground">
            {t('managed.projectSettings.overview.slugHelp')}
          </span>
        </label>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">
              {t('managed.projectSettings.overview.permission')}
            </dt>
            <dd className="mt-1 font-medium">
              {t(`managed.projectSettings.capability.${project.capability || 'read'}`)}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">
              {t('managed.projectSettings.overview.projectId')}
            </dt>
            <dd className="mt-1 break-all font-mono text-xs">{project.id}</dd>
          </div>
        </dl>
      </CardContent>
      <CardFooter className="justify-between gap-4">
        <p className="text-xs text-muted-foreground">
          {readOnly
            ? t('managed.projectSettings.overview.readOnly')
            : canEditSlug
              ? t('managed.projectSettings.overview.saveHint')
              : t('managed.projectSettings.overview.nameOnlyHint')}
        </p>
        <Button
          onClick={() => saveProject.mutate()}
          disabled={
            !dirty ||
            (nameChanged && !name.trim()) ||
            (slugChanged && !slug.trim()) ||
            saveProject.isPending
          }
        >
          {saveProject.isPending ? t('common.saving') : t('common.save')}
        </Button>
      </CardFooter>
    </Card>
  )
}

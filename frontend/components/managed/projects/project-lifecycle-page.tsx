'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, PauseCircle, PlayCircle, RotateCcw, Star } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

interface ProjectDetails {
  id: string
  name: string
  slug: string
  is_default: boolean
  triggers_paused?: boolean
  archived_at?: string | null
  capability?: string
}

export function ProjectLifecyclePage({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const { canAdmin } = useUserPermissionsContext()
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [archiveName, setArchiveName] = useState('')

  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => managedGet<ProjectDetails>(`auth/projects/${projectId}`),
  })

  const refreshProject = (project?: ProjectDetails) => {
    if (project) queryClient.setQueryData(['project', projectId], project)
    queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    queryClient.invalidateQueries({ queryKey: ['projects-list'] })
    queryClient.invalidateQueries({ queryKey: ['auth-me'] })
  }

  const setDefault = useMutation({
    mutationFn: () => managedPost<ProjectDetails>(`/auth/projects/${projectId}/set-default`, {}),
    onSuccess: refreshProject,
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })
  const setTriggersPaused = useMutation({
    mutationFn: (paused: boolean) =>
      managedPatch<ProjectDetails>(`/auth/projects/${projectId}`, { triggers_paused: paused }),
    onSuccess: refreshProject,
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })
  const archiveProject = useMutation({
    mutationFn: () => managedDelete(`/auth/projects/${projectId}`),
    onSuccess: () => {
      refreshProject()
      router.push('/managed/projects')
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })
  const restoreProject = useMutation({
    mutationFn: () => managedPost<ProjectDetails>(`/auth/projects/${projectId}/restore`, {}),
    onSuccess: (project) => {
      refreshProject(project)
      setArchiveName('')
    },
    onError: (error) => toastOperationError(t, error, 'common.operationFailed'),
  })

  if (projectQuery.isLoading) return <Skeleton className="h-96 w-full" />
  if (!projectQuery.data)
    return <p className="text-sm text-muted-foreground">{t('common.noData')}</p>

  const project = projectQuery.data
  const mutationPending =
    setDefault.isPending ||
    setTriggersPaused.isPending ||
    archiveProject.isPending ||
    restoreProject.isPending

  return (
    <div className="flex flex-col gap-6">
      <span className="sr-only">{project.name}</span>
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            {t('managed.projectSettings.lifecycle.operationsTitle')}
          </CardTitle>
          <CardDescription>
            {t('managed.projectSettings.lifecycle.operationsDescription')}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 rounded-lg border border-border p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium text-foreground">
                {t('managed.projectSettings.lifecycle.defaultTitle')}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {project.is_default
                  ? t('managed.projectSettings.lifecycle.defaultCurrent')
                  : t('managed.projectSettings.lifecycle.defaultDescription')}
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => setDefault.mutate()}
              disabled={
                !canAdmin || project.is_default || Boolean(project.archived_at) || mutationPending
              }
            >
              <Star data-icon="inline-start" />
              {t('manage.projects.setDefault')}
            </Button>
          </div>
          <div className="flex flex-col gap-3 rounded-lg border border-border p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium text-foreground">
                {t('managed.projectSettings.lifecycle.triggersTitle')}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {project.triggers_paused
                  ? t('managed.projectSettings.lifecycle.triggersPaused')
                  : t('managed.projectSettings.lifecycle.triggersRunning')}
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => setTriggersPaused.mutate(!project.triggers_paused)}
              disabled={!canAdmin || Boolean(project.archived_at) || mutationPending}
            >
              {project.triggers_paused ? (
                <PlayCircle data-icon="inline-start" />
              ) : (
                <PauseCircle data-icon="inline-start" />
              )}
              {project.triggers_paused
                ? t('manage.projects.resumeTriggers')
                : t('manage.projects.pauseTriggers')}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-lg">
            {t('managed.projectSettings.lifecycle.dangerTitle')}
          </CardTitle>
          <CardDescription>
            {t('managed.projectSettings.lifecycle.dangerDescription')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {project.is_default ? (
            <Alert>
              <AlertDescription>
                {t('managed.projectSettings.lifecycle.defaultArchiveBlocked')}
              </AlertDescription>
            </Alert>
          ) : project.archived_at ? (
            <p className="text-sm text-muted-foreground">
              {t('managed.projectSettings.lifecycle.archivedDescription')}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t('managed.projectSettings.lifecycle.archiveImpact')}
            </p>
          )}
        </CardContent>
        <CardFooter className="justify-end">
          {project.archived_at ? (
            <Button onClick={() => restoreProject.mutate()} disabled={!canAdmin || mutationPending}>
              <RotateCcw data-icon="inline-start" />
              {t('common.restore')}
            </Button>
          ) : (
            <Button
              variant="destructive"
              onClick={() => setArchiveOpen(true)}
              disabled={!canAdmin || project.is_default || mutationPending}
            >
              <Archive data-icon="inline-start" />
              {t('managed.projectSettings.lifecycle.archiveAction')}
            </Button>
          )}
        </CardFooter>
      </Card>

      <Dialog
        open={archiveOpen}
        onOpenChange={(open) => {
          setArchiveOpen(open)
          if (!open) setArchiveName('')
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projects.archiveTitle')}</DialogTitle>
            <DialogDescription>
              {t('managed.projectSettings.lifecycle.archiveDialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <p className="text-sm font-medium text-foreground">{project.name}</p>
            <Input
              value={archiveName}
              onChange={(event) => setArchiveName(event.target.value)}
              placeholder={t('managed.projectSettings.lifecycle.archiveNamePlaceholder')}
              autoComplete="off"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => archiveProject.mutate()}
              disabled={archiveName !== project.name || archiveProject.isPending}
            >
              {t('managed.projectSettings.lifecycle.confirmArchive')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

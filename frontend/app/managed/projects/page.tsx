'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, RotateCcw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import {
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  StatusBadge,
  type Column,
  type FilterDef,
  type MenuItem,
  PageHeader,
  ResourceErrorState,
} from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedPost, managedDelete } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { useUserPermissionsContext } from '@/providers/permissions-provider'
import { useProjectStore } from '@/stores/managed/project-store'

interface Project {
  id: string
  org_id: string
  name: string
  slug: string
  is_default: boolean
  triggers_paused?: boolean
  archived_at?: string | null
  created_at?: string
  project_role?: string | null
  capability?: string
}

interface ProjectScopedAction {
  runId: number
  scope: string
}

function projectSlugFromName(name: string) {
  return name
    .trim()
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

export default function ProjectsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const router = useRouter()
  const { canAdmin } = useUserPermissionsContext()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const orgScope = currentOrgId ?? ''
  const orgScopeRef = useRef(orgScope)
  const actionRunRef = useRef(0)
  const [showCreate, setShowCreate] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [newName, setNewName] = useState('')
  const [archiveTarget, setArchiveTarget] = useState<Project | null>(null)

  const {
    data: projects,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset: resetProjectsPagination,
  } = usePaginatedList<Project>({
    queryKey: 'projects-list',
    path: '/auth/projects',
    includeArchived: showArchived,
  })

  const resetCreateDraft = () => {
    setShowCreate(false)
    setNewName('')
  }

  const openCreateDialog = () => {
    actionRunRef.current += 1
    setShowCreate(true)
  }

  const handleCreateOpenChange = (open: boolean) => {
    if (!open) {
      actionRunRef.current += 1
    }
    setShowCreate(open)
  }

  useEffect(() => {
    if (orgScopeRef.current === orgScope) return
    orgScopeRef.current = orgScope
    actionRunRef.current += 1
    resetCreateDraft()
    setArchiveTarget(null)
    resetProjectsPagination()
  }, [orgScope, resetProjectsPagination])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  const getCurrentOrgScope = () => useProjectStore.getState().currentOrgId ?? ''

  const currentOrgScopeIsActive = (scope = orgScopeRef.current) =>
    orgScopeRef.current === scope && getCurrentOrgScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId && currentOrgScopeIsActive(scope)

  const nextScopedAction = (): ProjectScopedAction | null => {
    if (!currentOrgScopeIsActive()) return null
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    return {
      runId,
      scope: orgScopeRef.current,
    }
  }

  const currentMutableActiveProject = (project: Project | null) => {
    if (!project) return null
    if (!currentOrgScopeIsActive()) return null
    const current = queryClient
      .getQueriesData<{ data: Project[] }>({ queryKey: ['projects-list'] })
      .flatMap(([, page]) => page?.data ?? [])
      ?.find((candidate) => candidate.id === project.id)
    return current && !current.archived_at && !current.is_default ? current : null
  }

  const currentRestorableArchivedProject = (project: Project | null) => {
    if (!project) return null
    if (!currentOrgScopeIsActive()) return null
    const current = queryClient
      .getQueriesData<{ data: Project[] }>({ queryKey: ['projects-list'] })
      .flatMap(([, page]) => page?.data ?? [])
      ?.find((candidate) => candidate.id === project.id)
    return current?.archived_at ? current : null
  }

  const createProject = useMutation({
    mutationFn: (data: { name: string } & ProjectScopedAction) => {
      if (!isCurrentAction(data.runId, data.scope)) {
        throw new Error('Stale project create ignored')
      }
      const slug = projectSlugFromName(data.name) || `project-${Date.now().toString(36)}`
      return managedPost('/auth/projects', { name: data.name, slug })
    },
    onSuccess: (_data, variables) => {
      if (!isCurrentAction(variables.runId, variables.scope)) return
      resetProjectsPagination()
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      resetCreateDraft()
    },
    onError: (error, variables) => {
      if (!isCurrentAction(variables.runId, variables.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const archiveProject = useMutation({
    mutationFn: ({ projectId, runId, scope }: { projectId: string } & ProjectScopedAction) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale project archive ignored')
      }
      return managedDelete(`/auth/projects/${projectId}`)
    },
    onSuccess: (_data, variables) => {
      if (!isCurrentAction(variables.runId, variables.scope)) return
      resetProjectsPagination()
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
    },
    onError: (error, variables) => {
      if (!isCurrentAction(variables.runId, variables.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const openArchiveDialog = (project: Project) => {
    const current = currentMutableActiveProject(project)
    if (!current) return

    actionRunRef.current += 1
    setArchiveTarget(current)
  }

  const closeArchiveDialog = () => {
    actionRunRef.current += 1
    setArchiveTarget(null)
  }

  const restoreProject = useMutation({
    mutationFn: ({ projectId, runId, scope }: { projectId: string } & ProjectScopedAction) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale project restore ignored')
      }
      return managedPost(`/auth/projects/${projectId}/restore`, {})
    },
    onSuccess: (_data, variables) => {
      if (!isCurrentAction(variables.runId, variables.scope)) return
      resetProjectsPagination()
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error, variables) => {
      if (!isCurrentAction(variables.runId, variables.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  useEffect(() => {
    const currentById = new Map(projects.map((project) => [project.id, project]))
    const isMutableActiveProject = (project: Project | undefined) =>
      !!project && !project.archived_at && !project.is_default

    setArchiveTarget((target) => {
      if (!target) return null
      return isMutableActiveProject(currentById.get(target.id)) ? target : null
    })
  }, [projects])

  const filteredProjects = projects.filter(
    (p) =>
      (showArchived || !p.archived_at) &&
      filterByCreatedTime(p.created_at || '', createdFilter) &&
      matchesSearch(searchQuery, [
        p.id,
        p.name,
        p.slug,
        p.is_default ? 'default' : '',
        p.triggers_paused ? 'paused' : '',
        p.archived_at ? 'archived' : 'active',
      ]),
  )
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]
  const columns: Column<Project>[] = [
    {
      key: 'name',
      header: t('manage.projects.projectName'),
      render: (project) => (
        <div className="flex items-center gap-2">
          <span className="font-medium text-foreground">{project.name}</span>
          {project.is_default && (
            <Badge variant="outline" className="text-[10px]">
              {t('manage.projects.default')}
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: 'slug',
      header: t('manage.projects.slug'),
      render: (project) => <MonoId id={project.slug} truncate={false} />,
    },
    {
      key: 'status',
      header: t('manage.projects.status'),
      render: (project) => (
        <StatusBadge
          status={project.archived_at ? 'archived' : project.triggers_paused ? 'paused' : 'active'}
        />
      ),
    },
    {
      key: 'created',
      header: t('managed.table.created'),
      render: (project) =>
        project.created_at ? (
          <RelativeTime date={project.created_at} />
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
  ]

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="project"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['projects-list'] })}
      />
    )
  }

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.projects.title')}
        subtitle={t('manage.projects.subtitle')}
        action={
          canAdmin ? (
            <Button size="sm" onClick={openCreateDialog}>
              <Plus className="mr-1 h-4 w-4" />
              {t('manage.projects.create')}
            </Button>
          ) : null
        }
      />

      {showCreate && (
        <Dialog open={showCreate} onOpenChange={handleCreateOpenChange}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t('manage.projects.create')}</DialogTitle>
              <DialogDescription>{t('manage.projects.subtitle')}</DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2 py-2">
              <Input
                placeholder={t('manage.projects.namePlaceholder')}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t('manage.projects.slugGeneratedHint')}
              </p>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => handleCreateOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button
                onClick={() => {
                  const action = nextScopedAction()
                  if (action) createProject.mutate({ name: newName.trim(), ...action })
                }}
                disabled={!newName.trim() || createProject.isPending}
              >
                {t('manage.projects.create')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      <FilterBar
        searchPlaceholder={t('managed.search.projects')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />

      <DataTable
        columns={columns}
        data={filteredProjects}
        onRowClick={(project) => router.push(`/managed/projects/${project.id}`)}
        loading={isLoading}
        fetching={isFetching}
        emptyMessage={t('manage.projects.empty')}
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
        actionMenu={(project) => {
          if (project.archived_at) {
            return canAdmin
              ? [
                  {
                    label: t('common.restore'),
                    icon: <RotateCcw className="h-3.5 w-3.5" />,
                    onClick: () => {
                      const current = currentRestorableArchivedProject(project)
                      if (!current) return
                      const action = nextScopedAction()
                      if (action) restoreProject.mutate({ projectId: current.id, ...action })
                    },
                  },
                ]
              : []
          }

          const items: MenuItem[] = []
          if (canAdmin && !project.is_default) {
            items.push({
              label: t('common.archive'),
              icon: <Archive className="h-3.5 w-3.5" />,
              onClick: () => openArchiveDialog(project),
            })
          }
          return items
        }}
      />

      <Dialog open={!!archiveTarget} onOpenChange={(open) => !open && closeArchiveDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projects.archiveTitle')}</DialogTitle>
            <DialogDescription>{t('manage.projects.archiveDesc')}</DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">{archiveTarget?.name}</p>
          <DialogFooter>
            <Button variant="outline" onClick={closeArchiveDialog}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const current = currentMutableActiveProject(archiveTarget)
                if (!current) {
                  closeArchiveDialog()
                  return
                }
                const action = nextScopedAction()
                if (!action) return
                archiveProject.mutate({
                  projectId: current.id,
                  ...action,
                })
                setArchiveTarget(null)
              }}
            >
              {t('manage.projects.archive')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

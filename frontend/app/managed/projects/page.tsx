'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, Play, Plus } from 'lucide-react'
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
import { useProjectContext } from '@/hooks/managed/use-project-context'
import { managedPost } from '@/lib/api-client'
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
    .normalize('NFKD')
    .toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

export default function ProjectsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const router = useRouter()
  const { switchProject } = useProjectContext()
  const { canAdmin } = useUserPermissionsContext()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const currentOrganization = useProjectStore((state) =>
    state.organizations.find((organization) => organization.id === state.currentOrgId),
  )
  const canCreateProject =
    canAdmin || currentOrganization?.project_creation_policy === 'all_members'
  const orgScope = currentOrgId ?? ''
  const orgScopeRef = useRef(orgScope)
  const actionRunRef = useRef(0)
  const [showCreate, setShowCreate] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [newName, setNewName] = useState('')
  const [switchingProjectId, setSwitchingProjectId] = useState<string | null>(null)

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

  const renderProjectActions = (project: Project, fullWidth = false) => (
    <div className={fullWidth ? 'grid gap-2 sm:grid-cols-2' : 'flex justify-end gap-2'}>
      {project.id !== currentProjectId && !project.archived_at ? (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className={fullWidth ? 'w-full' : undefined}
          disabled={switchingProjectId !== null}
          onClick={() => {
            setSwitchingProjectId(project.id)
            void switchProject(project.id, project.org_id)
              .catch((error) => toastOperationError(t, error, 'common.operationFailed'))
              .finally(() => setSwitchingProjectId(null))
          }}
        >
          <Play className="h-3.5 w-3.5" />
          {t('manage.projects.use')}
        </Button>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={fullWidth ? 'w-full' : undefined}
        onClick={() => router.push(`/managed/projects/${project.id}`)}
      >
        {t(project.capability === 'admin' ? 'manage.projects.manage' : 'manage.projects.view')}
        <ArrowRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  )

  const columns: Column<Project>[] = [
    {
      key: 'name',
      header: t('manage.projects.projectName'),
      render: (project) => (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="link"
            className="h-auto justify-start p-0 font-medium"
            onClick={() => router.push(`/managed/projects/${project.id}`)}
          >
            {project.name}
          </Button>
          {project.is_default && (
            <Badge variant="outline" className="text-[10px]">
              {t('manage.projects.default')}
            </Badge>
          )}
          {project.id === currentProjectId && (
            <Badge variant="secondary" className="gap-1 text-[10px]">
              <Check className="h-3 w-3" />
              {t('manage.projects.current')}
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: 'permission',
      header: t('manage.projects.permission'),
      render: (project) => (
        <Badge variant="secondary">
          {t(`managed.projectSettings.capability.${project.capability || 'read'}`)}
        </Badge>
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
    {
      key: 'manage',
      header: t('managed.table.actions'),
      align: 'right',
      truncate: false,
      render: (project) => renderProjectActions(project),
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
          canCreateProject ? (
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
        loading={isLoading}
        fetching={isFetching}
        emptyMessage={t('manage.projects.empty')}
        mobileCard={(project) => (
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-foreground">{project.name}</span>
                {project.is_default ? (
                  <Badge variant="outline" className="text-[10px]">
                    {t('manage.projects.default')}
                  </Badge>
                ) : null}
                {project.id === currentProjectId ? (
                  <Badge variant="secondary" className="gap-1 text-[10px]">
                    <Check className="h-3 w-3" />
                    {t('manage.projects.current')}
                  </Badge>
                ) : null}
              </div>
              <MonoId id={project.slug} truncate={false} />
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">
                  {t('manage.projects.permission')}
                </div>
                <Badge variant="secondary">
                  {t(`managed.projectSettings.capability.${project.capability || 'read'}`)}
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">{t('manage.projects.status')}</div>
                <StatusBadge
                  status={
                    project.archived_at ? 'archived' : project.triggers_paused ? 'paused' : 'active'
                  }
                />
              </div>
            </div>
            {renderProjectActions(project, true)}
          </div>
        )}
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
      />
    </div>
  )
}

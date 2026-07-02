'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost, managedPatch, managedDelete } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Plus, Star, Pencil, Archive, Trash2, RotateCcw } from 'lucide-react'
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
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

interface Project {
  id: string
  org_id: string
  name: string
  slug: string
  is_default: boolean
  archived_at?: string | null
  created_at?: string
}

export default function ProjectsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { canAdmin } = useUserPermissionsContext()
  const [showCreate, setShowCreate] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [newName, setNewName] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [archiveTarget, setArchiveTarget] = useState<Project | null>(null)

  const {
    data: projects = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['projects-list', showArchived],
    queryFn: async () => managedGet<Project[]>(`/auth/projects?include_archived=${showArchived}`),
  })

  const createProject = useMutation({
    mutationFn: (data: { name: string; slug: string }) => managedPost('/auth/projects', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      setShowCreate(false)
      setNewName('')
      setNewSlug('')
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const setDefault = useMutation({
    mutationFn: (projectId: string) => managedPost(`/auth/projects/${projectId}/set-default`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const archiveProject = useMutation({
    mutationFn: (projectId: string) => managedDelete(`/auth/projects/${projectId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const [editTarget, setEditTarget] = useState<Project | null>(null)
  const [editName, setEditName] = useState('')

  const editProject = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      managedPatch(`/auth/projects/${id}`, { name }),
    onSuccess: () => {
      setEditTarget(null)
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null)

  const restoreProject = useMutation({
    mutationFn: (projectId: string) => managedPost(`/auth/projects/${projectId}/restore`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteProject = useMutation({
    mutationFn: (projectId: string) => managedDelete(`/auth/projects/${projectId}`),
    onSuccess: () => {
      setDeleteTarget(null)
      queryClient.invalidateQueries({ queryKey: ['projects-list'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
    onError: (error) => {
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
      render: (project) => <StatusBadge status={project.archived_at ? 'archived' : 'active'} />,
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
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="mr-1 h-4 w-4" />
              {t('manage.projects.create')}
            </Button>
          ) : null
        }
      />

      {showCreate && (
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t('manage.projects.create')}</DialogTitle>
              <DialogDescription>{t('manage.projects.subtitle')}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <Input
                placeholder={t('manage.projects.namePlaceholder')}
                value={newName}
                onChange={(e) => {
                  setNewName(e.target.value)
                  setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-'))
                }}
              />
              <Input
                placeholder={t('manage.projects.slugPlaceholder')}
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowCreate(false)}>
                {t('common.cancel')}
              </Button>
              <Button
                onClick={() => createProject.mutate({ name: newName, slug: newSlug })}
                disabled={!newName.trim() || !newSlug.trim()}
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
        emptyMessage={t('manage.projects.empty')}
        actionMenu={
          canAdmin
            ? (project) => {
                if (project.archived_at) {
                  return [
                    {
                      label: t('common.restore'),
                      icon: <RotateCcw className="h-3.5 w-3.5" />,
                      onClick: () => restoreProject.mutate(project.id),
                    },
                  ]
                }

                const items: MenuItem[] = [
                  {
                    label: t('common.edit'),
                    icon: <Pencil className="h-3.5 w-3.5" />,
                    onClick: () => {
                      setEditTarget(project)
                      setEditName(project.name)
                    },
                  },
                ]

                if (!project.is_default) {
                  items.push(
                    {
                      label: t('manage.projects.setDefault'),
                      icon: <Star className="h-3.5 w-3.5" />,
                      onClick: () => setDefault.mutate(project.id),
                    },
                    {
                      label: t('common.archive'),
                      icon: <Archive className="h-3.5 w-3.5" />,
                      onClick: () => setArchiveTarget(project),
                    },
                    {
                      label: t('common.delete'),
                      icon: <Trash2 className="h-3.5 w-3.5" />,
                      destructive: true,
                      onClick: () => setDeleteTarget(project),
                    },
                  )
                }

                return items
              }
            : undefined
        }
      />

      <Dialog open={!!archiveTarget} onOpenChange={(open) => !open && setArchiveTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projects.archiveTitle')}</DialogTitle>
            <DialogDescription>{t('manage.projects.archiveDesc')}</DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">{archiveTarget?.name}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                archiveProject.mutate(archiveTarget!.id)
                setArchiveTarget(null)
              }}
            >
              {t('manage.projects.archive')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Project Dialog */}
      <Dialog open={editTarget !== null} onOpenChange={(open) => !open && setEditTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projects.edit')}</DialogTitle>
            <DialogDescription>{t('manage.projects.editDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <label className="text-sm font-medium">{t('manage.projects.projectName')}</label>
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              placeholder={t('manage.projects.namePlaceholder')}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={() =>
                editTarget && editProject.mutate({ id: editTarget.id, name: editName.trim() })
              }
              disabled={!editName.trim() || editProject.isPending}
            >
              {editProject.isPending ? t('common.loading') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Project Dialog */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.projects.delete')}</DialogTitle>
            <DialogDescription>
              {t('manage.projects.deleteConfirm', { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteTarget && deleteProject.mutate(deleteTarget.id)}
              disabled={deleteProject.isPending}
            >
              {deleteProject.isPending ? t('common.loading') : t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

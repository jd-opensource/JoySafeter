'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Play, Pencil, History, Trash2, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { CreateScheduleDialog } from '@/components/managed/schedules/create-schedule-dialog'
import {
  PageHeader,
  FilterBar,
  type FilterDef,
  DataTable,
  type Column,
  StatusBadge,
  MonoId,
  RelativeTime,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import { useTranslation } from '@/lib/i18n'
import { describeCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { useManagedRequestScope } from '@/lib/managed/request-scope'
import { toastSuccess } from '@/lib/utils/toast'
import {
  useSchedules,
  useToggleSchedule,
  useTriggerSchedule,
  useDeleteSchedule,
  type Schedule,
} from '@/lib/managed/schedules'
import { useProjectStore } from '@/stores/managed/project-store'

const PAGE_SIZE_OPTIONS = [10, 25, 50]

export default function ScheduleListPage() {
  const { t } = useTranslation()
  const locale = (t('_locale') === 'zh' ? 'zh' : 'en') as 'en' | 'zh'
  const router = useRouter()
  const queryClient = useQueryClient()
  const projectReadOnly = useCurrentProjectReadOnly()
  const currentOrgId = useProjectStore((s) => s.currentOrgId)
  const currentProjectId = useProjectStore((s) => s.currentProjectId)
  const requestScope = useManagedRequestScope()
  const managedScope = requestScope.key || `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const managedScopeRef = useRef(managedScope)
  const managedRequestScopeRef = useRef(requestScope)

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Schedule | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Schedule | null>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])

  const schedulesQuery = useSchedules()
  const toggleMut = useToggleSchedule()
  const triggerMut = useTriggerSchedule()
  const deleteMut = useDeleteSchedule()

  const schedules = schedulesQuery.data ?? []

  // Client-side filter. Schedules are project-scoped and typically low-count, so
  // the backend returns them all; filtering/pagination happen here. If a project
  // ever exceeds the backend's list cap this must move to server-side `q`+offset.
  const filtered = useMemo(
    () =>
      schedules.filter(
        (s) =>
          matchesSearch(searchQuery, [s.name, s.description, s.cron_expr, s.id]) &&
          filterByCreatedTime(s.created_at, createdFilter) &&
          (statusFilter === 'all' || (statusFilter === 'enabled' ? s.enabled : !s.enabled)),
      ),
    [schedules, searchQuery, createdFilter, statusFilter],
  )

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const clampedPage = Math.min(page, totalPages)
  const paged = filtered.slice((clampedPage - 1) * pageSize, clampedPage * pageSize)

  // Reset to the first page whenever the filter inputs change.
  useEffect(() => {
    setPage(1)
  }, [searchQuery, createdFilter, statusFilter, pageSize])

  // Clear transient dialog state when the active project/org changes.
  useEffect(() => {
    if (managedScopeRef.current !== managedScope) {
      setCreateOpen(false)
      setEditTarget(null)
      setDeleteTarget(null)
    }
    managedScopeRef.current = managedScope
    managedRequestScopeRef.current = requestScope
  }, [managedScope, requestScope])

  useEffect(() => {
    if (projectReadOnly) {
      setCreateOpen(false)
      setEditTarget(null)
      setDeleteTarget(null)
    }
  }, [projectReadOnly])

  const handleToggle = async (s: Schedule, enabled: boolean) => {
    if (!currentProjectAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    if (managedScopeRef.current !== requestScope.key) return
    try {
      await toggleMut.mutateAsync({ id: s.id, enabled, requestScope })
    } catch (err) {
      toastOperationError(t, err, 'managed.schedules.toggleFailed')
    }
  }

  const handleTrigger = async (s: Schedule) => {
    if (!currentProjectAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    if (managedScopeRef.current !== requestScope.key) return
    try {
      await triggerMut.mutateAsync({ id: s.id, requestScope })
      toastSuccess(t('managed.schedules.triggered', { name: s.name }))
    } catch (err) {
      toastOperationError(t, err, 'managed.schedules.triggerFailed')
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget || !currentProjectAllowsWrite()) {
      setDeleteTarget(null)
      return
    }
    const requestScope = managedRequestScopeRef.current
    if (managedScopeRef.current !== requestScope.key) {
      setDeleteTarget(null)
      return
    }
    try {
      await deleteMut.mutateAsync({ id: deleteTarget.id, requestScope })
    } catch (err) {
      toastOperationError(t, err, 'managed.schedules.deleteFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
    {
      key: 'status',
      label: t('managed.schedules.statusFilter'),
      value: statusFilter,
      onChange: setStatusFilter,
      options: [
        { value: 'all', label: t('managed.schedules.filterAll') },
        { value: 'enabled', label: t('managed.schedules.filterEnabled') },
        { value: 'disabled', label: t('managed.schedules.filterDisabled') },
      ],
    },
  ]

  const columns: Column<Schedule>[] = [
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => (
        <div className="min-w-0">
          <span className="font-medium text-foreground">{s.name}</span>
          {s.description && (
            <p className="truncate text-xs text-muted-foreground">{s.description}</p>
          )}
        </div>
      ),
    },
    {
      key: 'cron',
      header: t('managed.schedules.schedule'),
      render: (s) => (
        <div className="min-w-0">
          <span className="text-sm text-foreground">{describeCron(s.cron_expr, locale)}</span>
          <p className="font-mono text-xs text-muted-foreground">
            {s.cron_expr} · {s.timezone}
          </p>
        </div>
      ),
    },
    {
      key: 'next_run',
      header: t('managed.schedules.nextRun'),
      render: (s) =>
        s.enabled && s.next_run_at ? (
          <span className="text-xs text-muted-foreground">
            <RelativeTime date={s.next_run_at} />
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      width: '10%',
      render: (s) => <StatusBadge status={s.enabled ? 'active' : 'idle'} />,
    },
    {
      key: 'enabled',
      header: t('managed.schedules.enabled'),
      width: '8%',
      render: (s) => (
        <div onClick={(e) => e.stopPropagation()}>
          <Switch
            checked={s.enabled}
            disabled={projectReadOnly}
            onCheckedChange={(checked) => handleToggle(s, checked)}
            aria-label={t('managed.schedules.enabled')}
          />
        </div>
      ),
    },
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (s) => <MonoId id={s.id} />,
    },
  ]

  if (schedulesQuery.isError) {
    return (
      <ResourceErrorState
        error={schedulesQuery.error}
        resource="schedule"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['schedules', requestScope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.schedules.title')}
        subtitle={t('managed.schedules.subtitle')}
        action={
          projectReadOnly ? null : (
            <Button
              size="sm"
              onClick={() => {
                if (!currentProjectAllowsWrite()) return
                if (managedScopeRef.current !== managedRequestScopeRef.current.key) return
                setCreateOpen(true)
              }}
            >
              <Plus className="h-4 w-4" />
              {t('managed.schedules.new')}
            </Button>
          )
        }
      />

      <FilterBar
        searchPlaceholder={t('managed.search.schedules')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />

      <DataTable
        columns={columns}
        data={paged}
        loading={schedulesQuery.isLoading}
        fetching={schedulesQuery.isFetching}
        onRowClick={(s) => router.push(`/managed/schedules/${s.id}`)}
        actionMenu={(s) =>
          projectReadOnly
            ? [
                {
                  label: t('managed.schedules.viewRuns'),
                  icon: <History className="h-3.5 w-3.5" />,
                  onClick: () => router.push(`/managed/schedules/${s.id}`),
                },
              ]
            : [
                {
                  label: t('managed.schedules.runNow'),
                  icon: <Play className="h-3.5 w-3.5" />,
                  onClick: () => handleTrigger(s),
                },
                {
                  label: t('common.edit'),
                  icon: <Pencil className="h-3.5 w-3.5" />,
                  onClick: () => setEditTarget(s),
                },
                {
                  label: t('managed.schedules.viewRuns'),
                  icon: <History className="h-3.5 w-3.5" />,
                  onClick: () => router.push(`/managed/schedules/${s.id}`),
                },
                {
                  label: t('common.delete'),
                  destructive: true,
                  separator: true,
                  icon: <Trash2 className="h-3.5 w-3.5" />,
                  onClick: () => setDeleteTarget(s),
                },
              ]
        }
        pagination={{
          hasNext: clampedPage < totalPages,
          hasPrev: clampedPage > 1,
          page: clampedPage,
          totalPages,
          pageSize,
          pageSizeOptions: PAGE_SIZE_OPTIONS,
          onNext: () => setPage((p) => Math.min(totalPages, p + 1)),
          onPrev: () => setPage((p) => Math.max(1, p - 1)),
          onPageChange: (p) => setPage(p),
          onPageSizeChange: (n) => setPageSize(n),
        }}
        emptyMessage={t('managed.schedules.empty')}
      />

      <CreateScheduleDialog
        open={!projectReadOnly && createOpen}
        onOpenChange={(open) => {
          if (open && !currentProjectAllowsWrite()) return
          if (open && managedScopeRef.current !== managedRequestScopeRef.current.key) return
          setCreateOpen(open)
        }}
      />

      <CreateScheduleDialog
        open={!projectReadOnly && !!editTarget}
        schedule={editTarget}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null)
        }}
      />

      <ConfirmDialog
        open={!projectReadOnly && !!deleteTarget}
        title={t('managed.schedules.deleteTitle')}
        description={t('managed.schedules.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}

'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Play, Pencil, History, Trash2, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

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
import { CreateTriggerDialog } from '@/components/managed/triggers/create-trigger-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { useTranslation } from '@/lib/i18n'
import { describeCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import {
  fireResultToastMessage,
  formatRunOnce,
  triggerLifecycleStatus,
} from '@/lib/managed/trigger-format'
import {
  useAgentTriggers,
  useToggleAgentTrigger,
  useRunTrigger,
  useDeleteAgentTrigger,
  type AgentTrigger,
  type TriggerType,
} from '@/lib/managed/triggers'
import { toastSuccess } from '@/lib/utils/toast'

const PAGE_SIZE_OPTIONS = [10, 25, 50]

export default function TriggerListPage() {
  const { t } = useTranslation()
  const locale = (t('_locale') === 'zh' ? 'zh' : 'en') as 'en' | 'zh'
  const router = useRouter()
  const queryClient = useQueryClient()
  const { scope, readOnly, scopeIsActive } = useScopedActions({
    onReset: () => {
      setCreateOpen(false)
      setEditTarget(null)
      setDeleteTarget(null)
    },
  })

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<AgentTrigger | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AgentTrigger | null>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])

  const triggersQuery = useAgentTriggers()
  const toggleMut = useToggleAgentTrigger()
  const runMut = useRunTrigger()
  const deleteMut = useDeleteAgentTrigger()

  const triggers = useMemo(() => triggersQuery.data ?? [], [triggersQuery.data])

  // Triggers are project-scoped and typically low-count, so the backend returns
  // them all; filtering/pagination happen client-side (mirrors schedules).
  const filtered = useMemo(() => {
    const matchesStatus = (trig: AgentTrigger) => {
      const lifecycleStatus = triggerLifecycleStatus(trig)
      switch (statusFilter) {
        case 'enabled':
          return lifecycleStatus === 'active'
        case 'disabled':
          return lifecycleStatus === 'idle'
        case 'auto_disabled':
          return lifecycleStatus === 'auto_disabled'
        case 'completed':
          return lifecycleStatus === 'completed'
        default:
          return true
      }
    }
    return triggers.filter(
      (trig) =>
        matchesSearch(searchQuery, [trig.name, trig.description, trig.cron_expr, trig.id]) &&
        filterByCreatedTime(trig.created_at, createdFilter) &&
        (typeFilter === 'all' || trig.type === typeFilter) &&
        matchesStatus(trig),
    )
  }, [triggers, searchQuery, createdFilter, typeFilter, statusFilter])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const clampedPage = Math.min(page, totalPages)
  const paged = filtered.slice((clampedPage - 1) * pageSize, clampedPage * pageSize)

  const resetPage = () => setPage(1)

  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    resetPage()
  }

  const handleCreatedFilterChange = (value: string) => {
    setCreatedFilter(value)
    resetPage()
  }

  const handleTypeFilterChange = (value: string) => {
    setTypeFilter(value)
    resetPage()
  }

  const handleStatusFilterChange = (value: string) => {
    setStatusFilter(value)
    resetPage()
  }

  const handlePageSizeChange = (value: number) => {
    setPageSize(value)
    resetPage()
  }

  const handleToggle = async (trig: AgentTrigger, enabled: boolean) => {
    if (!currentProjectAllowsWrite() || !scopeIsActive()) return
    try {
      await toggleMut.mutateAsync({ id: trig.id, enabled })
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.toggleFailed')
    }
  }

  const handleRun = async (trig: AgentTrigger) => {
    if (!currentProjectAllowsWrite() || !scopeIsActive()) return
    try {
      const res = await runMut.mutateAsync({ id: trig.id })
      toastSuccess(fireResultToastMessage(t, res.status, trig.name, res.reason))
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.fireFailed')
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget || !currentProjectAllowsWrite() || !scopeIsActive()) {
      setDeleteTarget(null)
      return
    }
    try {
      await deleteMut.mutateAsync(deleteTarget.id)
    } catch (err) {
      toastOperationError(t, err, 'managed.triggers.deleteFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: handleCreatedFilterChange,
    },
    {
      key: 'type',
      label: t('managed.triggers.typeFilter'),
      value: typeFilter,
      onChange: handleTypeFilterChange,
      options: [
        { value: 'all', label: t('managed.triggers.filterAll') },
        { value: 'cron', label: t('managed.triggers.typeOption.cron') },
        { value: 'webhook', label: t('managed.triggers.typeOption.webhook') },
        { value: 'manual', label: t('managed.triggers.typeOption.manual') },
      ],
    },
    {
      key: 'status',
      label: t('managed.triggers.statusFilter'),
      value: statusFilter,
      onChange: handleStatusFilterChange,
      options: [
        { value: 'all', label: t('managed.triggers.filterAll') },
        { value: 'enabled', label: t('managed.triggers.filterEnabled') },
        { value: 'disabled', label: t('managed.triggers.filterDisabled') },
        { value: 'completed', label: t('managed.triggers.filterCompleted') },
        { value: 'auto_disabled', label: t('managed.triggers.filterAutoDisabled') },
      ],
    },
  ]

  const renderTypeBadge = (type: TriggerType) => (
    <Badge variant="outline">{t(`managed.triggers.typeOption.${type}`)}</Badge>
  )

  const renderSummary = (trig: AgentTrigger) => {
    if (trig.type === 'cron') {
      if (trig.run_at) {
        return <span className="text-sm text-foreground">{formatRunOnce(t, trig.run_at)}</span>
      }
      return (
        <div className="min-w-0">
          <span className="text-sm text-foreground">
            {trig.cron_expr ? describeCron(trig.cron_expr, locale) : '—'}
          </span>
          {trig.cron_expr && (
            <p className="font-mono text-xs text-muted-foreground">
              {trig.cron_expr} · {trig.timezone}
            </p>
          )}
        </div>
      )
    }
    if (trig.type === 'webhook') {
      return (
        <span className="text-sm text-muted-foreground">
          {trig.secret_ref
            ? t('managed.triggers.signedVia', { secret: trig.secret_ref })
            : t('managed.triggers.unsigned')}
        </span>
      )
    }
    return (
      <span className="text-sm text-muted-foreground">{t('managed.triggers.manualSummary')}</span>
    )
  }

  const renderStatus = (trig: AgentTrigger) => {
    const lifecycleStatus = triggerLifecycleStatus(trig)
    if (lifecycleStatus === 'auto_disabled') {
      return (
        <span title={trig.disabled_reason ?? undefined}>
          <StatusBadge status="auto_disabled" />
        </span>
      )
    }
    return <StatusBadge status={lifecycleStatus} />
  }

  const columns: Column<AgentTrigger>[] = [
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (trig) => (
        <div className="min-w-0">
          <span className="font-medium text-foreground">{trig.name}</span>
          {trig.description && (
            <p className="truncate text-xs text-muted-foreground">{trig.description}</p>
          )}
        </div>
      ),
    },
    {
      key: 'type',
      header: t('managed.triggers.type'),
      width: '10%',
      render: (trig) => renderTypeBadge(trig.type),
    },
    {
      key: 'summary',
      header: t('managed.triggers.schedule'),
      render: renderSummary,
    },
    {
      key: 'next_run',
      header: t('managed.triggers.nextRun'),
      render: (trig) =>
        trig.enabled && trig.next_run_at ? (
          <span className="text-xs text-muted-foreground">
            <RelativeTime date={trig.next_run_at} />
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      width: '12%',
      render: renderStatus,
    },
    {
      key: 'agent',
      header: t('managed.triggers.agent'),
      width: '12%',
      render: (trig) => <MonoId id={trig.agent_id} />,
    },
    {
      key: 'enabled',
      header: t('managed.triggers.enabled'),
      width: '8%',
      render: (trig) => (
        <div onClick={(e) => e.stopPropagation()}>
          <Switch
            checked={trig.enabled}
            disabled={readOnly}
            onCheckedChange={(checked) => handleToggle(trig, checked)}
            aria-label={t('managed.triggers.enabled')}
          />
        </div>
      ),
    },
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (trig) => <MonoId id={trig.id} />,
    },
  ]

  if (triggersQuery.isError) {
    return (
      <ResourceErrorState
        error={triggersQuery.error}
        resource="trigger"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['triggers', scope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.triggers.title')}
        subtitle={t('managed.triggers.subtitle')}
        action={
          readOnly ? null : (
            <Button
              size="sm"
              onClick={() => {
                if (!currentProjectAllowsWrite() || !scopeIsActive()) return
                setCreateOpen(true)
              }}
            >
              <Plus className="h-4 w-4" />
              {t('managed.triggers.new')}
            </Button>
          )
        }
      />

      <FilterBar
        searchPlaceholder={t('managed.search.triggers')}
        searchValue={searchQuery}
        onSearchChange={handleSearchChange}
        filters={filters}
      />

      <DataTable
        columns={columns}
        data={paged}
        loading={triggersQuery.isLoading}
        fetching={triggersQuery.isFetching}
        onRowClick={(trig) => router.push(`/managed/triggers/${trig.id}`)}
        actionMenu={(trig) =>
          readOnly
            ? [
                {
                  label: t('managed.triggers.viewRuns'),
                  icon: <History className="h-3.5 w-3.5" />,
                  onClick: () => router.push(`/managed/triggers/${trig.id}`),
                },
              ]
            : [
                {
                  label: t('managed.triggers.runNow'),
                  icon: <Play className="h-3.5 w-3.5" />,
                  onClick: () => handleRun(trig),
                },
                {
                  label: t('common.edit'),
                  icon: <Pencil className="h-3.5 w-3.5" />,
                  onClick: () => setEditTarget(trig),
                },
                {
                  label: t('managed.triggers.viewRuns'),
                  icon: <History className="h-3.5 w-3.5" />,
                  onClick: () => router.push(`/managed/triggers/${trig.id}`),
                },
                {
                  label: t('common.delete'),
                  destructive: true,
                  separator: true,
                  icon: <Trash2 className="h-3.5 w-3.5" />,
                  onClick: () => setDeleteTarget(trig),
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
          onPageSizeChange: handlePageSizeChange,
        }}
        emptyMessage={t('managed.triggers.empty')}
      />

      <CreateTriggerDialog
        open={!readOnly && createOpen}
        onOpenChange={(open) => {
          if (open && (!currentProjectAllowsWrite() || !scopeIsActive())) return
          setCreateOpen(open)
        }}
      />

      <CreateTriggerDialog
        open={!readOnly && !!editTarget}
        trigger={editTarget}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null)
        }}
      />

      <ConfirmDialog
        open={!readOnly && !!deleteTarget}
        title={t('managed.triggers.deleteTitle')}
        description={t('managed.triggers.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}

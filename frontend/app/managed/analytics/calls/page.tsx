'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useMemo, useState } from 'react'

import { AnalyticsFilterBar } from '@/components/managed/analytics/analytics-filter-bar'
import { CallDetailDrawer } from '@/components/managed/analytics/call-detail-drawer'
import {
  DataTable,
  MonoId,
  PageHeader,
  RelativeTime,
  StatusBadge,
} from '@/components/managed/shared'
import type { Column } from '@/components/managed/shared/data-table'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { formatCompactNumber, formatDuration } from '@/lib/managed/analytics/formatters'
import { useCallsList, useAgentsForFilters } from '@/lib/managed/analytics/hooks'
import type { AnalyticsFilters, CallRecord } from '@/lib/managed/analytics/types'
import { cn } from '@/lib/utils'
import { tryParseAgentId } from '@/types/entity-id'

export default function CallsPage() {
  const { t } = useTranslation()
  const searchParams = useSearchParams()
  const initialAgentId = searchParams.get('agent_id')
  const [filters, setFilters] = useState<AnalyticsFilters>({
    range: '7d',
    engine: null,
    model: null,
    status: null,
    agent_id: tryParseAgentId(initialAgentId),
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedCall, setSelectedCall] = useState<CallRecord | null>(null)
  const [sortBy, setSortBy] = useState('created_at')
  const [sortOrder, setSortOrder] = useState('desc')

  const handleFiltersChange = (newFilters: AnalyticsFilters) => {
    setFilters(newFilters)
    setPage(1)
  }

  const handleSort = (field: string) => {
    if (sortBy === field) {
      setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(field)
      setSortOrder('desc')
    }
    setPage(1)
  }

  const calls = useCallsList(filters, page, pageSize, sortBy, sortOrder)
  const agentsList = useAgentsForFilters()

  const maxDuration = useMemo(() => {
    if (!calls.data?.data?.length) return 1
    return Math.max(...calls.data.data.map((r) => r.duration_ms || 0), 1)
  }, [calls.data])

  const engines = useMemo(() => {
    if (!agentsList.data) return undefined
    return [...new Set(agentsList.data.map((a) => a.engine_kind).filter(Boolean))]
  }, [agentsList.data])

  const agents = useMemo(() => {
    if (!agentsList.data) return undefined
    return agentsList.data.map((a) => ({ id: a.id, name: a.name }))
  }, [agentsList.data])

  const columns: Column<CallRecord>[] = [
    {
      key: 'time',
      header: t('analytics.calls.columns.time'),
      render: (row) => <RelativeTime date={row.started_at} />,
      width: '140px',
    },
    {
      key: 'session',
      header: t('analytics.calls.columns.session'),
      render: (row) =>
        row.session_id ? (
          <Link href={`/managed/sessions/${row.session_id}`}>
            <MonoId id={row.session_id} />
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      width: '120px',
    },
    {
      key: 'agent',
      header: t('analytics.calls.columns.agent'),
      render: (row) =>
        row.agent_id ? (
          <Link
            href={`/managed/agents/${row.agent_id}`}
            className="truncate text-sm transition-colors hover:text-foreground"
          >
            {row.agent_name}
          </Link>
        ) : (
          <span className="text-sm text-muted-foreground">—</span>
        ),
      width: '120px',
    },
    {
      key: 'engine',
      header: t('analytics.calls.columns.engine'),
      render: (row) => (
        <Badge variant="outline" className="text-xs">
          {row.engine_kind}
        </Badge>
      ),
      width: '80px',
    },
    {
      key: 'model',
      header: t('analytics.calls.columns.model'),
      render: (row) => <span className="truncate text-sm text-muted-foreground">{row.model}</span>,
      width: '120px',
    },
    {
      key: 'status',
      header: t('analytics.calls.columns.status'),
      render: (row) => {
        if (row.error && (row.status === 'error' || row.status === 'timeout')) {
          return (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help">
                    <StatusBadge status={row.status} />
                  </span>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[320px] text-xs">
                  {row.error}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )
        }
        return <StatusBadge status={row.status} />
      },
      width: '80px',
    },
    {
      key: 'retries',
      header: t('analytics.calls.columns.retries'),
      render: (row) => {
        if (!row.retry_count) return <span className="text-muted-foreground">—</span>
        return (
          <span
            className={cn(
              'text-xs font-medium tabular-nums',
              row.retry_count >= 3
                ? 'text-red-600 dark:text-red-400'
                : 'text-amber-600 dark:text-amber-400',
            )}
          >
            {row.retry_count}×
          </span>
        )
      },
      width: '60px',
    },
    {
      key: 'inputTokens',
      header: t('analytics.calls.columns.inputTokens'),
      render: (row) => (
        <span className="text-sm tabular-nums">{formatCompactNumber(row.input_tokens)}</span>
      ),
      width: '90px',
    },
    {
      key: 'outputTokens',
      header: t('analytics.calls.columns.outputTokens'),
      render: (row) => (
        <span className="text-sm tabular-nums">{formatCompactNumber(row.output_tokens)}</span>
      ),
      width: '90px',
    },
    {
      key: 'ttft',
      header: t('analytics.calls.columns.ttft'),
      render: (row) => (
        <span className="text-sm tabular-nums text-muted-foreground">
          {row.ttft_ms != null ? formatDuration(row.ttft_ms) : '—'}
        </span>
      ),
      width: '70px',
    },
    {
      key: 'duration',
      header: t('analytics.calls.columns.duration'),
      render: (row) => (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-muted/30">
            <div
              className={cn(
                'h-full rounded-full',
                row.duration_ms > 60000 ? 'bg-amber-500' : 'bg-[var(--chart-1)]',
              )}
              style={{ width: `${Math.min((row.duration_ms / maxDuration) * 100, 100)}%` }}
            />
          </div>
          <span className="text-sm tabular-nums">{formatDuration(row.duration_ms)}</span>
        </div>
      ),
      width: '140px',
    },
    {
      key: 'queueWait',
      header: t('analytics.calls.columns.queueWait'),
      render: (row) => (
        <span
          className={cn(
            'text-sm tabular-nums',
            row.queue_wait_ms > 30000
              ? 'text-amber-600 dark:text-amber-400'
              : 'text-muted-foreground',
          )}
        >
          {formatDuration(row.queue_wait_ms)}
        </span>
      ),
      width: '80px',
    },
  ]

  const totalPages = calls.data ? Math.ceil(calls.data.total / pageSize) : 0

  return (
    <div className="space-y-5">
      <PageHeader title={t('analytics.calls.title')} subtitle={t('analytics.calls.subtitle')} />
      <AnalyticsFilterBar
        filters={filters}
        onFiltersChange={handleFiltersChange}
        showStatusFilter
        engines={engines}
        agents={agents}
      />

      {/* Sort controls */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{t('analytics.calls.sortBy')}:</span>
        {[
          { key: 'created_at', label: t('analytics.calls.columns.time') },
          { key: 'duration_ms', label: t('analytics.calls.columns.duration') },
          { key: 'retry_count', label: t('analytics.calls.columns.retries') },
        ].map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => handleSort(opt.key)}
            className={cn(
              'rounded-md px-2 py-1 transition-colors',
              sortBy === opt.key
                ? 'bg-primary text-primary-foreground'
                : 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
            )}
          >
            {opt.label} {sortBy === opt.key && (sortOrder === 'desc' ? '↓' : '↑')}
          </button>
        ))}
      </div>

      <DataTable
        columns={columns}
        data={calls.data?.data ?? []}
        loading={calls.isLoading}
        fetching={calls.isFetching}
        onRowClick={(row) => setSelectedCall(row)}
        emptyMessage={t('analytics.calls.noRecords')}
        pagination={{
          hasNext: calls.data?.has_more ?? false,
          hasPrev: page > 1,
          onNext: () => setPage((p) => p + 1),
          onPrev: () => setPage((p) => Math.max(1, p - 1)),
          page,
          totalPages,
          onPageChange: setPage,
          pageSize,
          pageSizeOptions: [10, 20, 50],
          onPageSizeChange: (size) => {
            setPageSize(size)
            setPage(1)
          },
        }}
      />

      <CallDetailDrawer
        call={selectedCall}
        open={!!selectedCall}
        onClose={() => setSelectedCall(null)}
      />
    </div>
  )
}

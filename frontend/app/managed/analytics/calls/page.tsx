'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { AnalyticsFilters, CallRecord } from '@/lib/managed/analytics/types'
import { useCallsList, useAgentsForFilters, useErrorSummary, useLatencyStats, useTimeHeatmap } from '@/lib/managed/analytics/hooks'
import {
  formatCompactNumber,
  formatDuration,
  formatCost,
} from '@/lib/managed/analytics/formatters'
import { AnalyticsFilterBar } from '@/components/managed/analytics/analytics-filter-bar'
import { ErrorSummaryCard } from '@/components/managed/analytics/error-summary-card'
import { LatencyStatsCard } from '@/components/managed/analytics/latency-stats-card'
import { TimeHeatmap } from '@/components/managed/analytics/time-heatmap'
import { DataTable, StatusBadge, MonoId, RelativeTime, PageHeader } from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { CallDetailDrawer } from '@/components/managed/analytics/call-detail-drawer'
import type { Column } from '@/components/managed/shared/data-table'

export default function CallsPage() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<AnalyticsFilters>({
    range: '7d',
    engine: null,
    model: null,
    status: null,
    agent_id: null,
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedCall, setSelectedCall] = useState<CallRecord | null>(null)

  const handleFiltersChange = (newFilters: AnalyticsFilters) => {
    setFilters(newFilters)
    setPage(1)
  }

  const calls = useCallsList(filters, page, pageSize)
  const agentsList = useAgentsForFilters()
  const errorSummary = useErrorSummary(filters)
  const latencyStats = useLatencyStats(filters)
  const heatmap = useTimeHeatmap(filters)

  const maxDuration = useMemo(() => {
    if (!calls.data?.data?.length) return 1
    return Math.max(...calls.data.data.map(r => r.duration_ms || 0), 1)
  }, [calls.data])

  const engines = useMemo(() => {
    if (!agentsList.data) return undefined
    return [...new Set(agentsList.data.map(a => a.engine_kind).filter(Boolean))]
  }, [agentsList.data])

  const agents = useMemo(() => {
    if (!agentsList.data) return undefined
    return agentsList.data.map(a => ({ id: a.id, name: a.name }))
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
      render: (row) => row.session_id ? (
        <Link href={`/managed/sessions/${row.session_id}`}>
          <MonoId id={row.session_id} />
        </Link>
      ) : <span className="text-muted-foreground">—</span>,
      width: '120px',
    },
    {
      key: 'agent',
      header: t('analytics.calls.columns.agent'),
      render: (row) => row.agent_id ? (
        <Link href={`/managed/agents/${row.agent_id}`} className="text-sm truncate hover:text-foreground transition-colors">
          {row.agent_name}
        </Link>
      ) : <span className="text-sm text-muted-foreground">—</span>,
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
      render: (row) => (
        <span className="text-sm truncate text-muted-foreground">{row.model}</span>
      ),
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
                  <span className="cursor-help"><StatusBadge status={row.status} /></span>
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
          <div className="w-16 h-1.5 bg-muted/30 rounded-full overflow-hidden shrink-0">
            <div
              className={cn(
                'h-full rounded-full',
                row.duration_ms > 60000 ? 'bg-amber-500' : 'bg-[var(--chart-1)]'
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
      key: 'cost',
      header: t('analytics.calls.columns.cost'),
      render: (row) => (
        <span className="text-sm tabular-nums text-muted-foreground">
          {formatCost(row.cost)}
        </span>
      ),
      width: '70px',
    },
  ]

  const totalPages = calls.data
    ? Math.ceil(calls.data.total / pageSize)
    : 0

  return (
    <div className="space-y-5">
      <PageHeader
        title={t('analytics.calls.title')}
        subtitle={t('analytics.calls.subtitle')}
      />
      <AnalyticsFilterBar
        filters={filters}
        onFiltersChange={handleFiltersChange}
        showStatusFilter
        engines={engines}
        agents={agents}
      />

      {/* Error and latency summary cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <ErrorSummaryCard data={errorSummary.data} loading={errorSummary.isLoading} />
        <LatencyStatsCard data={latencyStats.data} loading={latencyStats.isLoading} />
      </div>

      {/* Time pattern heatmap */}
      <TimeHeatmap data={heatmap.data ?? []} loading={heatmap.isLoading} />

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

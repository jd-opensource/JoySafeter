'use client'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import {
  formatPercent,
  formatDuration,
  formatCost,
  formatCompactNumber,
} from '@/lib/managed/analytics/formatters'
import type { AgentMetrics } from '@/lib/managed/analytics/types'

interface AgentComparisonProps {
  data: AgentMetrics[]
  loading?: boolean
  fetching?: boolean
}

interface MetricRow {
  labelKey: string
  key: string
  format: (v: number) => string
  bestFn: 'max' | 'min'
}

const METRIC_ROWS: MetricRow[] = [
  { labelKey: 'analytics.agentComparison.metrics.sessions', key: 'total_sessions', format: formatCompactNumber, bestFn: 'max' },
  { labelKey: 'analytics.agentComparison.metrics.tasks', key: 'total_tasks', format: formatCompactNumber, bestFn: 'max' },
  { labelKey: 'analytics.agentComparison.metrics.successRate', key: 'success_rate', format: formatPercent, bestFn: 'max' },
  { labelKey: 'analytics.agentComparison.metrics.avgDuration', key: 'avg_duration_ms', format: formatDuration, bestFn: 'min' },
  { labelKey: 'analytics.agentComparison.metrics.avgTtft', key: 'avg_ttft_ms', format: formatDuration, bestFn: 'min' },
  { labelKey: 'analytics.agentComparison.metrics.avgCost', key: 'avg_cost', format: formatCost, bestFn: 'min' },
  { labelKey: 'analytics.agentComparison.metrics.totalTokens', key: 'total_tokens', format: formatCompactNumber, bestFn: 'max' },
  { labelKey: 'analytics.agentComparison.metrics.avgSteps', key: 'avg_agent_steps', format: (v: number) => v.toFixed(1), bestFn: 'min' },
]

function getBestIndex(values: number[], fn: 'max' | 'min'): number {
  if (values.length === 0) return -1
  let bestIdx = 0
  for (let i = 1; i < values.length; i++) {
    if (fn === 'max' && values[i] > values[bestIdx]) bestIdx = i
    if (fn === 'min' && values[i] < values[bestIdx]) bestIdx = i
  }
  return bestIdx
}

function LoadingSkeleton() {
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <div className="bg-muted/30 px-4 py-2.5">
        <div className="h-3 w-24 animate-pulse rounded bg-muted" />
      </div>
      <div className="space-y-0">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 border-t border-border px-4 py-3">
            <div className="h-3 w-24 animate-pulse rounded bg-muted" />
            <div className="ml-auto h-3 w-16 animate-pulse rounded bg-muted" />
            <div className="h-3 w-16 animate-pulse rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function AgentComparison({
  data,
  loading = false,
  fetching = false,
}: AgentComparisonProps) {
  const { t } = useTranslation()

  if (loading) return <LoadingSkeleton />

  if (data.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-border bg-card">
        <p className="text-sm text-muted-foreground">{t('analytics.agentComparison.noAgents')}</p>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'rounded-lg border border-border overflow-hidden',
        fetching && 'opacity-50 transition-opacity',
      )}
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t('analytics.agentComparison.metricLabel')}
            </th>
            {data.map((a) => (
              <th
                key={a.agent_id}
                className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground"
              >
                <div className="flex flex-col items-end gap-0.5">
                  <span>{a.agent_name}</span>
                  <span className="text-[10px] font-normal normal-case opacity-60">
                    {a.engine_kind}
                  </span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map((row) => {
            const values = data.map(
              (a) => (a as unknown as Record<string, number>)[row.key] ?? 0,
            )
            const bestIdx = getBestIndex(values, row.bestFn)

            return (
              <tr key={row.key} className="border-t border-border hover:bg-accent/20">
                <td className="px-4 py-2.5 text-xs text-muted-foreground">
                  {t(row.labelKey)}
                </td>
                {values.map((v, i) => (
                  <td
                    key={data[i].agent_id}
                    className={cn(
                      'px-4 py-2.5 text-right tabular-nums',
                      i === bestIdx ? 'font-semibold text-foreground' : 'text-muted-foreground',
                    )}
                  >
                    {row.format(v)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

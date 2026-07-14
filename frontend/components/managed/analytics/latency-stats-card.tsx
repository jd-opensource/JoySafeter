'use client'

import { useTranslation } from '@/lib/i18n'
import { formatDuration } from '@/lib/managed/analytics/formatters'
import type { LatencyStats } from '@/lib/managed/analytics/types'

interface LatencyStatsCardProps {
  data: LatencyStats | undefined
  loading?: boolean
}

export function LatencyStatsCard({ data, loading }: LatencyStatsCardProps) {
  const { t } = useTranslation()

  if (loading || !data) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="h-4 w-24 animate-pulse rounded bg-muted mb-3" />
        <div className="h-16 animate-pulse rounded bg-muted" />
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-medium text-foreground mb-3">
        {t('analytics.latencyStats.title')}
      </h3>

      {/* Percentile bars */}
      <div className="space-y-2.5">
        <PercentileRow label="P50" value={data.p50_ms} max={data.p99_ms} color="bg-emerald-500" />
        <PercentileRow label="P95" value={data.p95_ms} max={data.p99_ms} color="bg-amber-500" />
        <PercentileRow label="P99" value={data.p99_ms} max={data.p99_ms} color="bg-red-500" />
      </div>

      {/* Slow call count */}
      {data.slow_count > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          {t('analytics.latencyStats.slowCalls', { count: data.slow_count, total: data.total_calls })}
        </p>
      )}
    </div>
  )
}

function PercentileRow({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-mono text-muted-foreground w-7">{label}</span>
      <div className="flex-1 h-2 bg-muted/30 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max(pct, 3)}%` }} />
      </div>
      <span className="text-xs tabular-nums text-foreground w-16 text-right">{formatDuration(value)}</span>
    </div>
  )
}

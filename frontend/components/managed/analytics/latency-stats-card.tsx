'use client'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { LatencyStats } from '@/lib/managed/analytics/types'

interface LatencyStatsCardProps {
  data: LatencyStats | undefined
  loading?: boolean
}

const COLOR_MAP = {
  emerald: 'bg-emerald-500',
  amber: 'bg-amber-500',
  red: 'bg-red-500',
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

  if (!data.buckets.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">
          {t('analytics.latencyStats.title')}
        </h3>
        <p className="text-xs text-muted-foreground">{t('analytics.charts.noData')}</p>
      </div>
    )
  }

  const maxCount = Math.max(...data.buckets.map(b => b.count), 1)

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground">
          {t('analytics.latencyStats.title')}
        </h3>
        <span className="text-xs text-muted-foreground">
          {data.total_calls} {t('analytics.latencyStats.totalTasks')}
        </span>
      </div>

      <div className="space-y-2">
        {data.buckets.map((bucket) => (
          <div key={bucket.label} className="flex items-center gap-2.5">
            <span className="text-xs text-muted-foreground w-14 shrink-0 text-right tabular-nums">
              {bucket.label}
            </span>
            <div className="flex-1 h-4 bg-muted/20 rounded overflow-hidden">
              <div
                className={cn('h-full rounded', COLOR_MAP[bucket.color] || 'bg-gray-400')}
                style={{ width: `${(bucket.count / maxCount) * 100}%`, minWidth: bucket.count > 0 ? '4px' : '0' }}
              />
            </div>
            <span className="text-xs tabular-nums text-foreground w-8 text-right">
              {bucket.count}
            </span>
            <span className="text-xs text-muted-foreground w-10 text-right tabular-nums">
              {bucket.pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

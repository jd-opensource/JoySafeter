'use client'

import { useTranslation } from '@/lib/i18n'
import type { ErrorSummary } from '@/lib/managed/analytics/types'
import { statusDotClass, statusLabelKey } from '@/lib/managed/status-tone'
import { cn } from '@/lib/utils'

interface ErrorSummaryCardProps {
  data: ErrorSummary | undefined
  loading?: boolean
}


export function ErrorSummaryCard({ data, loading }: ErrorSummaryCardProps) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="h-4 w-24 animate-pulse rounded bg-muted mb-3" />
        <div className="h-20 animate-pulse rounded bg-muted" />
      </div>
    )
  }

  if (!data || data.total_errors === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-foreground">
            {t('analytics.errorSummary.title')}
          </h3>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('analytics.errorSummary.noErrors')}
        </p>
      </div>
    )
  }

  const total = data.total_errors

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground">
          {t('analytics.errorSummary.title')}
        </h3>
        <span className="text-xs text-muted-foreground">
          {total} {t('analytics.errorSummary.total')}
        </span>
      </div>

      {/* Status breakdown bar */}
      <div className="flex h-3 rounded-full overflow-hidden gap-px mb-3">
        {data.status_breakdown.map((item) => (
          <div
            key={item.status}
            className={cn('h-full', statusDotClass(item.status))}
            style={{ width: `${(item.count / total) * 100}%`, minWidth: '4px' }}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3">
        {data.status_breakdown.map((item) => {
          const labelKey = statusLabelKey(item.status)
          return (
            <div key={item.status} className="flex items-center gap-1.5 text-xs">
              <div className={cn('h-2 w-2 rounded-full', statusDotClass(item.status))} />
              <span className="text-muted-foreground">{labelKey ? t(labelKey) : item.status}</span>
              <span className="font-medium text-foreground">{item.count}</span>
            </div>
          )
        })}
      </div>

      {/* Top error messages */}
      {data.top_errors.length > 0 && (
        <div className="border-t border-border pt-3">
          <h4 className="text-xs font-medium text-muted-foreground mb-2">
            {t('analytics.errorSummary.topErrors')}
          </h4>
          <div className="space-y-1.5">
            {data.top_errors.map((err, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="shrink-0 font-mono text-red-600 dark:text-red-400">{err.count}×</span>
                <span className="text-muted-foreground truncate">{err.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

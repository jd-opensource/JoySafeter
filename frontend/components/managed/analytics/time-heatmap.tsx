'use client'

import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { HeatmapCell } from '@/lib/managed/analytics/types'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'

interface TimeHeatmapProps {
  data: HeatmapCell[]
  loading?: boolean
}

const DAY_LABELS_KEY = [
  'analytics.heatmap.sun',
  'analytics.heatmap.mon',
  'analytics.heatmap.tue',
  'analytics.heatmap.wed',
  'analytics.heatmap.thu',
  'analytics.heatmap.fri',
  'analytics.heatmap.sat',
]

export function TimeHeatmap({ data, loading }: TimeHeatmapProps) {
  const { t } = useTranslation()

  const { grid, maxCount } = useMemo(() => {
    const grid: (HeatmapCell | null)[][] = Array.from({ length: 7 }, () => Array(24).fill(null))
    let maxCount = 1
    for (const cell of data) {
      grid[cell.day][cell.hour] = cell
      if (cell.count > maxCount) maxCount = cell.count
    }
    return { grid, maxCount }
  }, [data])

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 h-4 w-32 animate-pulse rounded bg-muted" />
        <div className="h-[140px] animate-pulse rounded bg-muted" />
      </div>
    )
  }

  if (!data.length) return null

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-sm font-medium text-foreground">{t('analytics.heatmap.title')}</h3>
      <p className="mb-3 text-xs text-muted-foreground">{t('analytics.heatmap.subtitle')}</p>

      <div className="overflow-x-auto">
        <div className="min-w-[600px]">
          {/* Hour labels */}
          <div className="mb-1 ml-8 flex items-start gap-0.5">
            {Array.from({ length: 24 }).map((_, h) => (
              <div key={h} className="flex-1 text-center">
                {h % 6 === 0 && <span className="text-[10px] text-muted-foreground">{h}</span>}
              </div>
            ))}
          </div>

          {/* Grid rows */}
          <TooltipProvider delayDuration={100}>
            {grid.map((row, dayIdx) => (
              <div key={dayIdx} className="mb-0.5 flex items-center gap-0.5">
                <span className="w-7 shrink-0 pr-1 text-right text-[10px] text-muted-foreground">
                  {t(DAY_LABELS_KEY[dayIdx])}
                </span>
                {row.map((cell, hourIdx) => {
                  const intensity = cell ? cell.count / maxCount : 0
                  const hasErrors = cell ? cell.error_count > 0 : false
                  return (
                    <Tooltip key={hourIdx}>
                      <TooltipTrigger asChild>
                        <div
                          className={cn(
                            'h-4 flex-1 cursor-default rounded-sm transition-colors',
                            !cell || cell.count === 0
                              ? 'bg-muted/20'
                              : hasErrors
                                ? 'bg-red-500'
                                : 'bg-[var(--chart-1)]',
                          )}
                          style={{
                            opacity: cell && cell.count > 0 ? Math.max(0.2, intensity) : 1,
                          }}
                        />
                      </TooltipTrigger>
                      {cell && cell.count > 0 && (
                        <TooltipContent side="top" className="text-xs">
                          <p>
                            {t(DAY_LABELS_KEY[dayIdx])} {hourIdx}:00–{hourIdx + 1}:00
                          </p>
                          <p>
                            {cell.count} {t('analytics.heatmap.calls')}
                            {cell.error_count > 0
                              ? `, ${cell.error_count} ${t('analytics.heatmap.errors')}`
                              : ''}
                          </p>
                        </TooltipContent>
                      )}
                    </Tooltip>
                  )
                })}
              </div>
            ))}
          </TooltipProvider>
        </div>
      </div>
    </div>
  )
}

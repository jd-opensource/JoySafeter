'use client'

import { cn } from '@/lib/utils'
import type { EngineShareItem } from '@/lib/managed/analytics/types'
import { useTranslation } from '@/lib/i18n'
import { ChartContainer } from './chart-container'
import { CHART_COLORS, ENGINE_COLOR_MAP, ENGINE_LABELS } from './constants'

interface EngineShareChartProps {
  data: EngineShareItem[]
  loading?: boolean
  fetching?: boolean
}

const MAX_ENGINES = 7

function consolidateEngines(data: EngineShareItem[]): EngineShareItem[] {
  if (data.length <= MAX_ENGINES) return data

  const sorted = [...data].sort((a, b) => b.count - a.count)
  const top = sorted.slice(0, MAX_ENGINES - 1)
  const rest = sorted.slice(MAX_ENGINES - 1)
  const otherCount = rest.reduce((sum, item) => sum + item.count, 0)
  const otherPct = rest.reduce((sum, item) => sum + item.percentage, 0)

  return [
    ...top,
    { engine: 'other', count: otherCount, percentage: otherPct },
  ]
}

function getEngineColor(engine: string): string {
  const idx = ENGINE_COLOR_MAP[engine] ?? ENGINE_COLOR_MAP.other ?? 7
  return CHART_COLORS[idx] ?? CHART_COLORS[7]
}

function getEngineLabel(engine: string): string {
  return ENGINE_LABELS[engine] ?? engine
}

export function EngineShareChart({
  data,
  loading,
  fetching,
}: EngineShareChartProps) {
  const { t } = useTranslation()
  const items = consolidateEngines(data)
  const total = items.reduce((sum, item) => sum + item.count, 0)

  return (
    <ChartContainer
      title={t('analytics.charts.engineShare')}
      tooltip={t('analytics.charts.engineShareTooltip')}
      loading={loading}
      fetching={fetching}
      empty={!data.length}
    >
      <div className="space-y-3">
        {/* Horizontal stacked bar */}
        <div className="flex h-6 gap-0.5 overflow-hidden rounded">
          {items.map((item) => {
            const widthPct = total > 0 ? (item.count / total) * 100 : 0
            return (
              <div
                key={item.engine}
                className="rounded-sm"
                style={{
                  width: `${widthPct}%`,
                  minWidth: item.count > 0 ? 4 : 0,
                  backgroundColor: getEngineColor(item.engine),
                }}
              />
            )
          })}
        </div>

        {/* Legend */}
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {items.map((item) => (
            <div
              key={item.engine}
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: getEngineColor(item.engine) }}
              />
              <span>{getEngineLabel(item.engine)}</span>
              <span className="font-medium text-foreground">
                {item.percentage.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </ChartContainer>
  )
}

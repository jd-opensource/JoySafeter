'use client'

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { LatencyTimePoint, TimeRange } from '@/lib/managed/analytics/types'
import {
  formatAxisTimestamp,
  formatAxisDuration,
  formatDuration,
} from '@/lib/managed/analytics/formatters'
import { useTranslation } from '@/lib/i18n'
import { ChartContainer } from './chart-container'

interface LatencyTrendChartProps {
  data: LatencyTimePoint[]
  range: TimeRange
  loading?: boolean
  fetching?: boolean
}

function CustomTooltip({ active, payload, label }: Record<string, unknown>) {
  if (!active || !Array.isArray(payload) || !payload.length) return null

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md">
      <p className="mb-1.5 text-xs text-muted-foreground">
        {String(label ?? '')}
      </p>
      {(payload as Record<string, unknown>[]).map((entry) => (
        <div key={String(entry.dataKey)} className="flex items-center gap-2 text-sm">
          <span
            className="inline-block h-0.5 w-3 rounded-full"
            style={{ backgroundColor: String(entry.color ?? '') }}
          />
          <span className="text-muted-foreground">{String(entry.name ?? '')}</span>
          <span className="ml-auto font-medium text-foreground">
            {formatDuration(entry.value as number)}
          </span>
        </div>
      ))}
    </div>
  )
}

function ChartLegend() {
  const { t } = useTranslation()

  return (
    <div className="flex items-center gap-4 text-xs">
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: 'var(--chart-1)' }}
        />
        <span className="text-muted-foreground">{t('analytics.charts.avgDuration')}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: 'var(--chart-2)' }}
        />
        <span className="text-muted-foreground">{t('analytics.charts.avgTtft')}</span>
      </div>
    </div>
  )
}

export function LatencyTrendChart({
  data,
  range,
  loading,
  fetching,
}: LatencyTrendChartProps) {
  const { t } = useTranslation()

  return (
    <ChartContainer
      title={t('analytics.charts.latencyTrend')}
      tooltip={t('analytics.charts.latencyTrendTooltip')}
      loading={loading}
      fetching={fetching}
      empty={!data.length}
      headerRight={<ChartLegend />}
    >
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="latencyDurationFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.1} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="latencyTtftFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-2)" stopOpacity={0.1} />
              <stop offset="100%" stopColor="var(--chart-2)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="0"
            stroke="var(--chart-grid)"
            vertical={false}
          />
          <XAxis
            dataKey="timestamp"
            tick={{ fontSize: 12, fill: 'var(--chart-axis)' }}
            tickLine={false}
            axisLine={{ stroke: 'var(--chart-grid)' }}
            tickFormatter={(v: string) => formatAxisTimestamp(v, range)}
          />
          <YAxis
            tick={{ fontSize: 12, fill: 'var(--chart-axis)' }}
            tickLine={false}
            axisLine={false}
            tickFormatter={formatAxisDuration}
          />
          <Tooltip content={CustomTooltip} />
          <Area
            type="monotone"
            dataKey="avg_duration_ms"
            name={t('analytics.charts.avgDuration')}
            stroke="var(--chart-1)"
            strokeWidth={2}
            fill="url(#latencyDurationFill)"
            fillOpacity={0.1}
            dot={false}
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="avg_ttft_ms"
            name={t('analytics.charts.avgTtft')}
            stroke="var(--chart-2)"
            strokeWidth={2}
            fill="url(#latencyTtftFill)"
            fillOpacity={0.1}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}

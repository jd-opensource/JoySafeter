'use client'

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { CallsTimePoint, TimeRange } from '@/lib/managed/analytics/types'
import { formatAxisTimestamp } from '@/lib/managed/analytics/formatters'
import { useTranslation } from '@/lib/i18n'
import { ChartContainer } from './chart-container'

interface CallsTrendChartProps {
  data: CallsTimePoint[]
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
      {payload.map((entry: Record<string, unknown>) => (
        <div key={String(entry.dataKey)} className="flex items-center gap-2 text-sm">
          <span
            className="inline-block h-0.5 w-3 rounded-full"
            style={{ backgroundColor: String(entry.color ?? '') }}
          />
          <span className="text-muted-foreground">{String(entry.name ?? '')}</span>
          <span className="ml-auto font-medium text-foreground">
            {((entry.value as number) ?? 0).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  )
}

export function CallsTrendChart({
  data,
  range,
  loading,
  fetching,
}: CallsTrendChartProps) {
  const { t } = useTranslation()

  return (
    <ChartContainer
      title={t('analytics.charts.callsTrend')}
      tooltip={t('analytics.charts.callsTrendTooltip')}
      loading={loading}
      fetching={fetching}
      empty={!data.length}
    >
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="callsTotalFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.1} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="callsErrorFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-5)" stopOpacity={0.1} />
              <stop offset="100%" stopColor="var(--chart-5)" stopOpacity={0} />
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
            tickFormatter={(v: number) => v.toLocaleString()}
          />
          <Tooltip content={CustomTooltip} />
          <Legend
            verticalAlign="top"
            align="right"
            iconType="plainline"
            wrapperStyle={{ fontSize: 12 }}
          />
          <Area
            type="monotone"
            dataKey="total_calls"
            name={t('analytics.charts.totalCalls')}
            stroke="var(--chart-1)"
            strokeWidth={2}
            fill="url(#callsTotalFill)"
            fillOpacity={0.1}
            dot={false}
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="error_calls"
            name={t('analytics.charts.errorCalls')}
            stroke="var(--chart-5)"
            strokeWidth={2}
            fill="url(#callsErrorFill)"
            fillOpacity={0.1}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}

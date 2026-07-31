'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { TokensTimePoint, TimeRange } from '@/lib/managed/analytics/types'
import {
  formatAxisTimestamp,
  formatAxisTokens,
  formatTokens,
} from '@/lib/managed/analytics/formatters'
import { useTranslation } from '@/lib/i18n'
import { ChartContainer } from './chart-container'

interface TokenTrendChartProps {
  data: TokensTimePoint[]
  range: TimeRange
  loading?: boolean
  fetching?: boolean
}

function CustomTooltip({ active, payload, label }: Record<string, unknown>) {
  const { t } = useTranslation()

  if (!active || !Array.isArray(payload) || !payload.length) return null

  const input =
    ((payload as Record<string, unknown>[]).find((p) => p.dataKey === 'input_tokens')
      ?.value as number) ?? 0
  const output =
    ((payload as Record<string, unknown>[]).find((p) => p.dataKey === 'output_tokens')
      ?.value as number) ?? 0
  const total = input + output

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md">
      <p className="mb-1.5 text-xs text-muted-foreground">{String(label ?? '')}</p>
      {(payload as Record<string, unknown>[]).map((entry) => (
        <div key={String(entry.dataKey)} className="flex items-center gap-2 text-sm">
          <span
            className="inline-block h-0.5 w-3 rounded-full"
            style={{ backgroundColor: String(entry.color ?? '') }}
          />
          <span className="text-muted-foreground">{String(entry.name ?? '')}</span>
          <span className="ml-auto font-medium text-foreground">
            {formatTokens(entry.value as number)}
          </span>
        </div>
      ))}
      <div className="mt-1 border-t border-border pt-1 text-sm">
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">{t('analytics.charts.total')}</span>
          <span className="font-medium text-foreground">{formatTokens(total)}</span>
        </div>
      </div>
    </div>
  )
}

function ChartLegend() {
  const { t } = useTranslation()

  return (
    <div className="flex items-center gap-4 text-xs">
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: 'var(--chart-1)' }}
        />
        <span className="text-muted-foreground">{t('analytics.charts.inputTokens')}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: 'var(--chart-2)' }}
        />
        <span className="text-muted-foreground">{t('analytics.charts.outputTokens')}</span>
      </div>
    </div>
  )
}

export function TokenTrendChart({ data, range, loading, fetching }: TokenTrendChartProps) {
  const { t } = useTranslation()

  return (
    <ChartContainer
      title={t('analytics.charts.tokenTrend')}
      tooltip={t('analytics.charts.tokenTrendTooltip')}
      loading={loading}
      fetching={fetching}
      empty={!data.length}
      headerRight={<ChartLegend />}
    >
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="0" stroke="var(--chart-grid)" vertical={false} />
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
            tickFormatter={formatAxisTokens}
          />
          <Tooltip content={CustomTooltip} />
          <Bar
            dataKey="input_tokens"
            name={t('analytics.charts.inputTokens')}
            stackId="tokens"
            fill="var(--chart-1)"
            radius={[0, 0, 0, 0]}
            maxBarSize={24}
            isAnimationActive={false}
          />
          <Bar
            dataKey="output_tokens"
            name={t('analytics.charts.outputTokens')}
            stackId="tokens"
            fill="var(--chart-2)"
            radius={[4, 4, 0, 0]}
            maxBarSize={24}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  )
}

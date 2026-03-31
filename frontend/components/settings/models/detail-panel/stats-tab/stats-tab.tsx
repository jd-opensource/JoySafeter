'use client'

import { useState } from 'react'

import { useModelUsageStats } from '@/hooks/queries/models'

import { SummaryCards } from './summary-cards'
import { UsageChart } from './usage-chart'

interface StatsTabProps {
  providerName: string
}

const PERIODS = [
  { label: '24h', value: '24h', granularity: 'hour' },
  { label: '7d', value: '7d', granularity: 'day' },
  { label: '30d', value: '30d', granularity: 'day' },
] as const

export function StatsTab({ providerName }: StatsTabProps) {
  const [period, setPeriod] = useState<'24h' | '7d' | '30d'>('24h')
  const granularity = PERIODS.find((p) => p.value === period)?.granularity ?? 'hour'

  const { data, isLoading } = useModelUsageStats({
    period,
    granularity,
    providerName,
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        {PERIODS.map((p) => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              period === p.value
                ? 'bg-[var(--surface-hover)] text-[var(--text-primary)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <SummaryCards summary={data?.summary} loading={isLoading} />

      {!isLoading && data && (
        <UsageChart timeline={data.timeline} byModel={data.by_model} />
      )}
    </div>
  )
}

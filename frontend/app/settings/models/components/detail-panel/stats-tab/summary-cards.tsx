'use client'

import type { UsageStatsSummary } from '@/types/models'

interface SummaryCardsProps {
  summary?: UsageStatsSummary
  loading?: boolean
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-base)] p-4">
      <div className="mb-2 h-3 w-20 animate-pulse rounded bg-[var(--surface-hover)]" />
      <div className="h-6 w-16 animate-pulse rounded bg-[var(--surface-hover)]" />
    </div>
  )
}

interface CardProps {
  label: string
  value: string
}

function StatCard({ label, value }: CardProps) {
  return (
    <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-base)] p-4">
      <p className="mb-1 text-xs text-[var(--text-muted)]">{label}</p>
      <p className="text-lg font-semibold text-[var(--text-primary)]">{value}</p>
    </div>
  )
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

export function SummaryCards({ summary, loading }: SummaryCardsProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  const totalTokens = (summary?.total_input_tokens ?? 0) + (summary?.total_output_tokens ?? 0)

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard label="总调用次数" value={String(summary?.total_calls ?? 0)} />
      <StatCard label="总 Token 数" value={formatTokens(totalTokens)} />
      <StatCard
        label="平均响应时间"
        value={`${(summary?.avg_response_time_ms ?? 0).toFixed(0)} ms`}
      />
      <StatCard
        label="错误率"
        value={`${((summary?.error_rate ?? 0) * 100).toFixed(1)}%`}
      />
    </div>
  )
}

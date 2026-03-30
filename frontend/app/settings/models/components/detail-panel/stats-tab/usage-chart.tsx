'use client'

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { UsageByModel, UsageTimelinePoint } from '@/types/models'
import { formatTokenCount } from './summary-cards'

interface UsageChartProps {
  timeline: UsageTimelinePoint[]
  byModel: UsageByModel[]
}

function formatTimestamp(ts: string, granularity?: string): string {
  const d = new Date(ts)
  if (granularity === 'day') {
    return `${d.getMonth() + 1}/${d.getDate()}`
  }
  return `${d.getHours()}:00`
}

export function UsageChart({ timeline, byModel }: UsageChartProps) {
  const hasData = timeline.length > 0 || byModel.length > 0

  if (!hasData) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-[var(--border-muted)] bg-[var(--surface-base)]">
        <p className="text-sm text-[var(--text-muted)]">暂无使用数据</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {timeline.length > 0 && (
        <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-base)] p-4">
          <p className="mb-3 text-xs font-medium text-[var(--text-secondary)]">调用趋势</p>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={timeline} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-muted)" />
              <XAxis
                dataKey="timestamp"
                tickFormatter={(v) => formatTimestamp(v)}
                tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
              />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <Tooltip
                contentStyle={{
                  background: 'var(--surface-elevated)',
                  border: '1px solid var(--border-muted)',
                  borderRadius: 6,
                  fontSize: 12,
                }}
                labelFormatter={(v) => formatTimestamp(String(v))}
              />
              <Line
                type="monotone"
                dataKey="calls"
                name="调用次数"
                stroke="var(--color-primary, #6366f1)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {byModel.length > 0 && (
        <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-base)] p-4">
          <p className="mb-3 text-xs font-medium text-[var(--text-secondary)]">模型排行</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-muted)] text-left text-xs text-[var(--text-muted)]">
                <th className="pb-2 font-medium">模型</th>
                <th className="pb-2 text-right font-medium">调用次数</th>
                <th className="pb-2 text-right font-medium">Token 数</th>
              </tr>
            </thead>
            <tbody>
              {byModel.map((row) => (
                <tr
                  key={row.model_name}
                  className="border-b border-[var(--border-muted)] last:border-0"
                >
                  <td className="py-2 text-[var(--text-primary)]">{row.model_name}</td>
                  <td className="py-2 text-right text-[var(--text-secondary)]">{row.calls}</td>
                  <td className="py-2 text-right text-[var(--text-secondary)]">
                    {formatTokenCount(row.tokens)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

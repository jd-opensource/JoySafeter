'use client'

import { motion } from 'framer-motion'
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Clock,
  BarChart3,
  Zap,
  Target,
  Timer,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import CountUp from 'react-countup'

import { cn } from '@/lib/core/utils/cn'
import { evaluationTasks, evalTaskDetails } from '@/mocks/evaluations'

const CHART_COLORS = ['#22c55e', '#ef4444']

export default function EvalDetailPage() {
  const { t } = useTranslation()
  const params = useParams<{ taskId: string }>()

  const task = evaluationTasks.find((et) => et.id === params.taskId)
  const details = evalTaskDetails[params.taskId]

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">Evaluation not found</p>
      </div>
    )
  }

  const metrics = details?.metrics
  const samples = details?.samples || []

  // Chart data
  const passedCount = samples.filter((s) => s.passed).length
  const failedCount = samples.length - passedCount
  const pieData = [
    { name: 'Passed', value: passedCount },
    { name: 'Failed', value: failedCount },
  ]
  const latencyData = samples.map((s) => ({
    name: s.id,
    latency: s.latencyMs,
  }))

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/evaluate"
          className="mb-4 inline-flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          <ArrowLeft className="h-3 w-3" /> Back to evaluations
        </Link>

        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">{task.name}</h1>
            <p className="mt-1 text-sm text-[var(--text-tertiary)]">
              {task.agentName} — {task.dataset} — {task.totalSamples} samples
            </p>
          </div>
          {task.accuracy !== null && (
            <div className="text-right">
              <p className="text-3xl font-bold text-[var(--status-healthy)]">
                <CountUp end={task.accuracy} duration={1.5} decimals={1} />%
              </p>
              <p className="text-xs text-[var(--text-muted)]">{t('evaluate.accuracy')}</p>
            </div>
          )}
        </div>
      </div>

      {/* Metrics Cards */}
      {metrics && (
        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            { key: 'accuracy', value: metrics.accuracy, suffix: '%', icon: Target },
            { key: 'precision', value: metrics.precision, suffix: '%', icon: Target },
            { key: 'recall', value: metrics.recall, suffix: '%', icon: Target },
            { key: 'f1Score', value: metrics.f1Score, suffix: '%', icon: BarChart3 },
            { key: 'avgLatency', value: metrics.avgLatencyMs, suffix: 'ms', icon: Timer },
            { key: 'p95Latency', value: metrics.p95LatencyMs, suffix: 'ms', icon: Zap },
          ].map((m, i) => {
            const Icon = m.icon
            return (
              <motion.div
                key={m.key}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-[var(--text-muted)]">{t(`evaluate.${m.key}`)}</span>
                  <Icon className="h-3 w-3 text-[var(--text-subtle)]" />
                </div>
                <p className="text-lg font-bold text-[var(--text-primary)]">
                  <CountUp end={m.value} duration={1} decimals={m.suffix === '%' ? 1 : 0} />{m.suffix}
                </p>
              </motion.div>
            )
          })}
        </div>
      )}

      {/* Charts */}
      {samples.length > 0 && (
        <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Pass/Fail Pie */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4">
            <h3 className="mb-4 text-xs font-semibold text-[var(--text-secondary)]">Pass / Fail Distribution</h3>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" label>
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Latency Bar */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4">
            <h3 className="mb-4 text-xs font-semibold text-[var(--text-secondary)]">Latency per Sample (ms)</h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={latencyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} stroke="var(--text-subtle)" />
                <YAxis tick={{ fontSize: 10 }} stroke="var(--text-subtle)" />
                <Tooltip />
                <Bar dataKey="latency" fill="var(--brand-500)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Sample Results Table */}
      {samples.length > 0 && (
        <>
          <h2 className="mb-3 text-sm font-semibold text-[var(--text-secondary)]">{t('evaluate.sampleResults')}</h2>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden">
            <div className="border-b border-[var(--border)] px-4 py-2.5 flex items-center text-[11px] font-medium text-[var(--text-muted)]">
              <span className="w-12">#</span>
              <span className="flex-1">{t('evaluate.input')}</span>
              <span className="w-20 text-center">{t('evaluate.expected')}</span>
              <span className="w-20 text-center">{t('evaluate.passed')}</span>
              <span className="w-20 text-center">{t('evaluate.latency')}</span>
            </div>
            {samples.map((sample, i) => (
              <motion.div
                key={sample.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.04 }}
                className={cn(
                  'flex items-center px-4 py-2.5 transition-colors hover:bg-[var(--surface-3)]',
                  i < samples.length - 1 && 'border-b border-[var(--border)]'
                )}
              >
                <span className="w-12 text-xs text-[var(--text-subtle)]">{i + 1}</span>
                <span className="flex-1 text-xs text-[var(--text-primary)] truncate pr-4">{sample.input}</span>
                <span className="w-20 text-center text-[10px] text-[var(--text-muted)]">{sample.expectedOutput}</span>
                <div className="w-20 flex items-center justify-center">
                  {sample.passed ? (
                    <CheckCircle2 className="h-4 w-4 text-[var(--status-healthy)]" />
                  ) : (
                    <XCircle className="h-4 w-4 text-[var(--status-offline)]" />
                  )}
                </div>
                <span className="w-20 text-center text-xs text-[var(--text-muted)]">{sample.latencyMs}ms</span>
              </motion.div>
            ))}
          </div>
        </>
      )}

      {/* No detail data message */}
      {!details && (
        <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-1)] p-12 text-center">
          <BarChart3 className="mx-auto h-8 w-8 text-[var(--text-subtle)] mb-3" />
          <p className="text-sm text-[var(--text-muted)]">
            Detailed results available for evaluation eval-001. Select that task to see sample-level data and charts.
          </p>
        </div>
      )}
    </div>
  )
}

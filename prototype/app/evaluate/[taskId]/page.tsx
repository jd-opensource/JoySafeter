'use client'

import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Clock,
  BarChart3,
  Zap,
  Target,
  Timer,
  Play,
  Pause,
  Square,
  Download,
  Ban,
  AlertCircle,
  Bot,
  Database,
  Calendar,
  Layers,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts'
import CountUp from 'react-countup'

import { cn } from '@/lib/core/utils/cn'
import { toastSuccess, toastInfo, toastError } from '@/lib/utils/toast'
import { evaluationTasks, evalTaskDetails, type EvalStatus, type EvaluationTask } from '@/mocks/evaluations'

const CHART_COLORS = ['#34d399', '#f43f5e']

const STATUS_CONFIG: Record<EvalStatus, { label: string; icon: React.ComponentType<{ className?: string }>; pill: string }> = {
  pending:   { label: 'Pending',   icon: Clock,        pill: 'text-amber-300 bg-amber-500/10 border border-amber-500/20' },
  running:   { label: 'Running',   icon: Play,         pill: 'text-sky-300 bg-sky-500/10 border border-sky-500/20' },
  paused:    { label: 'Paused',    icon: Pause,        pill: 'text-orange-300 bg-orange-500/10 border border-orange-500/20' },
  completed: { label: 'Completed', icon: CheckCircle2, pill: 'text-emerald-300 bg-emerald-500/10 border border-emerald-500/20' },
  failed:    { label: 'Failed',    icon: XCircle,      pill: 'text-rose-300 bg-rose-500/10 border border-rose-500/20' },
  cancelled: { label: 'Cancelled', icon: Ban,          pill: 'text-white/40 bg-white/5 border border-white/10' },
}

function formatDate(ts: string | null) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ==================== Confirm Dialog ====================
function ConfirmDialog({ open, title, description, confirmLabel, variant, onConfirm, onCancel }: {
  open: boolean; title: string; description: string; confirmLabel: string
  variant: 'danger' | 'warning'; onConfirm: () => void; onCancel: () => void
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
          <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.15 }}
            className="relative z-10 w-full max-w-sm rounded-2xl border border-violet-500/25 bg-[#0d0d14]/95 backdrop-blur-2xl p-6 shadow-[0_0_60px_rgba(0,0,0,0.8)]">
            <div className={cn('mb-4 flex h-10 w-10 items-center justify-center rounded-full border', variant === 'danger' ? 'bg-rose-500/15 border-rose-500/25' : 'bg-orange-500/15 border-orange-500/25')}>
              <AlertCircle className={cn('h-5 w-5', variant === 'danger' ? 'text-rose-400' : 'text-orange-400')} />
            </div>
            <h3 className="mb-1 text-base font-semibold text-white/90">{title}</h3>
            <p className="mb-6 text-sm text-white/45">{description}</p>
            <div className="flex gap-3">
              <button onClick={onCancel} className="flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white/70 transition-all hover:bg-white/8 hover:text-white/90">Cancel</button>
              <button onClick={onConfirm} className={cn('flex-1 rounded-xl px-4 py-2 text-sm font-semibold text-white transition-all border', variant === 'danger' ? 'bg-rose-600/80 hover:bg-rose-600 border-rose-500/30' : 'bg-orange-500/80 hover:bg-orange-500 border-orange-400/30')}>
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ==================== Main Page ====================

export default function EvalDetailPage() {
  const { t } = useTranslation()
  const params = useParams<{ taskId: string }>()

  const initialTask = evaluationTasks.find((et) => et.id === params.taskId)
  const [task, setTask] = useState<EvaluationTask | undefined>(initialTask)
  const [activeTab, setActiveTab] = useState<'overview' | 'results'>('overview')
  const [confirmState, setConfirmState] = useState<{
    open: boolean; title: string; description: string; confirmLabel: string
    variant: 'danger' | 'warning'; onConfirm: () => void
  }>({ open: false, title: '', description: '', confirmLabel: '', variant: 'danger', onConfirm: () => {} })

  const details = evalTaskDetails[params.taskId]

  // Auto-advance if running
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => {
    if (task?.status === 'running') {
      timerRef.current = setInterval(() => {
        setTask((prev) => {
          if (!prev || prev.status !== 'running') return prev
          const newProgress = Math.min(prev.progress + Math.random() * 3 + 1, 100)
          const newCompleted = Math.round((newProgress / 100) * prev.totalSamples)
          if (newProgress >= 100) {
            return { ...prev, progress: 100, completedSamples: prev.totalSamples, status: 'completed', accuracy: 90 + Math.random() * 8, completedAt: new Date().toISOString() }
          }
          return { ...prev, progress: Math.round(newProgress * 10) / 10, completedSamples: newCompleted }
        })
      }, 2000)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [task?.status])

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">Evaluation not found</p>
      </div>
    )
  }

  const metrics = details?.metrics
  const samples = details?.samples || []
  const passedCount = samples.filter((s) => s.passed).length
  const failedCount = samples.length - passedCount
  const pieData = [{ name: 'Passed', value: passedCount }, { name: 'Failed', value: failedCount }]
  const latencyData = samples.map((s) => ({ name: s.id, latency: s.latencyMs }))

  const cfg = STATUS_CONFIG[task.status]
  const StatusIcon = cfg.icon

  function handlePause() {
    setTask((prev) => prev ? { ...prev, status: 'paused' } : prev)
    if (timerRef.current) clearInterval(timerRef.current)
    toastInfo('Evaluation paused')
  }
  function handleResume() {
    setTask((prev) => prev ? { ...prev, status: 'running' } : prev)
    toastSuccess('Evaluation resumed')
  }
  function handleCancel() {
    setConfirmState({
      open: true, title: 'Cancel Evaluation', confirmLabel: 'Cancel Task', variant: 'warning',
      description: 'This will stop the evaluation. It cannot be resumed.',
      onConfirm: () => {
        setTask((prev) => prev ? { ...prev, status: 'cancelled', completedAt: new Date().toISOString() } : prev)
        if (timerRef.current) clearInterval(timerRef.current)
        setConfirmState((p) => ({ ...p, open: false }))
        toastInfo('Evaluation cancelled')
      },
    })
  }
  function handleDownload() {
    toastSuccess(`Downloading results for "${task?.name}"`)
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Back */}
      <Link href="/evaluate" className="mb-4 inline-flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]">
        <ArrowLeft className="h-3 w-3" /> Back to evaluations
      </Link>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">{task.name}</h1>
            <span className={cn('flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium', cfg.pill)}>
              <StatusIcon className="h-3 w-3" />
              {cfg.label}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
            <span className="flex items-center gap-1"><Bot className="h-3 w-3" />{task.agentName}</span>
            <span className="flex items-center gap-1"><Database className="h-3 w-3" />{task.dataset}</span>
            <span className="flex items-center gap-1"><Layers className="h-3 w-3" />{task.totalSamples} samples</span>
          </div>
          {/* Timestamps */}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-subtle)]">
            <span className="flex items-center gap-1"><Calendar className="h-3 w-3" />Created: {formatDate(task.createdAt)}</span>
            {task.startedAt && <span className="flex items-center gap-1"><Play className="h-3 w-3" />Started: {formatDate(task.startedAt)}</span>}
            {task.completedAt && <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3" />Ended: {formatDate(task.completedAt)}</span>}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {task.status === 'running' && (
            <>
              <button onClick={handlePause} className="flex items-center gap-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-300 transition-all hover:bg-amber-500/20">
                <Pause className="h-3.5 w-3.5" /> Pause
              </button>
              <button onClick={handleCancel} className="flex items-center gap-1.5 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 transition-all hover:bg-rose-500/20">
                <Square className="h-3.5 w-3.5" /> Cancel
              </button>
            </>
          )}
          {task.status === 'paused' && (
            <>
              <button onClick={handleResume} className="flex items-center gap-1.5 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3 py-1.5 text-xs font-medium text-violet-300 transition-all hover:bg-violet-500/20">
                <Play className="h-3.5 w-3.5" /> Resume
              </button>
              <button onClick={handleCancel} className="flex items-center gap-1.5 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 transition-all hover:bg-rose-500/20">
                <Square className="h-3.5 w-3.5" /> Cancel
              </button>
            </>
          )}
          {task.status === 'completed' && (
            <button onClick={handleDownload} className="flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition-all hover:bg-emerald-500/20">
              <Download className="h-3.5 w-3.5" /> Download
            </button>
          )}
          {task.accuracy !== null && (
            <div className="text-right pl-2 border-l border-[var(--border)]">
              <p className="text-2xl font-bold text-[var(--status-healthy)]">
                <CountUp end={task.accuracy} duration={1.5} decimals={1} />%
              </p>
              <p className="text-[10px] text-[var(--text-muted)]">Accuracy</p>
            </div>
          )}
        </div>
      </div>

      {/* Progress bar (for active tasks) */}
      {(task.status === 'running' || task.status === 'paused') && (
        <motion.div className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-medium text-[var(--text-secondary)]">
              {task.status === 'paused' ? 'Paused at' : 'Progress'} — {task.completedSamples}/{task.totalSamples} samples
            </span>
            <span className="font-bold text-[var(--brand-500)]">{Math.round(task.progress)}%</span>
          </div>
          <div className="h-2 w-full rounded-full bg-[var(--surface-5)] overflow-hidden">
            <motion.div
              className="h-full rounded-full"
              style={{ backgroundColor: task.status === 'paused' ? 'var(--status-degraded)' : 'var(--brand-500)' }}
              animate={{ width: `${task.progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </motion.div>
      )}

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-[var(--surface-3)] p-1 w-fit">
        {(['overview', 'results'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn('rounded-md px-4 py-1.5 text-xs font-medium transition-colors',
              activeTab === tab ? 'bg-[var(--surface-1)] text-[var(--text-primary)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            )}
          >
            {tab === 'overview' ? 'Overview' : 'Sample Results'}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {activeTab === 'overview' && (
          <motion.div key="overview" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>
            {/* Metrics Cards */}
            {metrics ? (
              <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                {[
                  { key: 'accuracy',   value: metrics.accuracy,    suffix: '%',  icon: Target,   color: 'text-emerald-400' },
                  { key: 'precision',  value: metrics.precision,   suffix: '%',  icon: Target,   color: 'text-sky-400' },
                  { key: 'recall',     value: metrics.recall,      suffix: '%',  icon: Target,   color: 'text-violet-400' },
                  { key: 'f1Score',    value: metrics.f1Score,     suffix: '%',  icon: BarChart3,color: 'text-indigo-400' },
                  { key: 'avgLatency', value: metrics.avgLatencyMs,suffix: 'ms', icon: Timer,    color: 'text-amber-400' },
                  { key: 'p95Latency', value: metrics.p95LatencyMs,suffix: 'ms', icon: Zap,      color: 'text-rose-400' },
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
                        <Icon className={cn('h-3 w-3', m.color)} />
                      </div>
                      <p className="text-lg font-bold text-[var(--text-primary)]">
                        <CountUp end={m.value} duration={1} decimals={m.suffix === '%' ? 1 : 0} />{m.suffix}
                      </p>
                    </motion.div>
                  )
                })}
              </div>
            ) : (
              <div className="mb-8 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-1)] p-10 text-center">
                <BarChart3 className="mx-auto h-8 w-8 text-[var(--text-subtle)] mb-3" />
                <p className="text-sm text-[var(--text-muted)]">
                  {task.status === 'running' || task.status === 'paused'
                    ? 'Metrics will appear when the evaluation completes.'
                    : 'Detailed metrics not available for this task.'}
                </p>
              </div>
            )}

            {/* Charts */}
            {samples.length > 0 && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4">
                  <h3 className="mb-4 text-xs font-semibold text-[var(--text-secondary)]">Pass / Fail Distribution</h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={75} dataKey="value" label={({ name, value }) => `${name}: ${value}`} labelLine={false}>
                        {pieData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i]} />)}
                      </Pie>
                      <Tooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
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
          </motion.div>
        )}

        {activeTab === 'results' && (
          <motion.div key="results" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>
            {samples.length > 0 ? (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden">
                <div className="border-b border-[var(--border)] px-4 py-2.5 flex items-center text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide bg-[var(--surface-3)]">
                  <span className="w-8">#</span>
                  <span className="flex-1">{t('evaluate.input')}</span>
                  <span className="w-24 text-center hidden sm:block">Expected</span>
                  <span className="w-28 text-center hidden md:block">Actual</span>
                  <span className="w-16 text-center">{t('evaluate.passed')}</span>
                  <span className="w-20 text-center">{t('evaluate.latency')}</span>
                </div>
                {samples.map((sample, i) => (
                  <motion.div
                    key={sample.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.04 }}
                    className={cn('flex items-center px-4 py-2.5 transition-colors hover:bg-[var(--surface-3)]', i < samples.length - 1 && 'border-b border-[var(--border)]')}
                  >
                    <span className="w-8 text-xs text-[var(--text-subtle)]">{i + 1}</span>
                    <span className="flex-1 text-xs text-[var(--text-primary)] truncate pr-4">{sample.input}</span>
                    <span className="w-24 text-center text-[10px] text-[var(--text-muted)] hidden sm:block">{sample.expectedOutput}</span>
                    <span className="w-28 text-center text-[10px] text-[var(--text-muted)] hidden md:block truncate">{sample.actualOutput}</span>
                    <div className="w-16 flex items-center justify-center">
                      {sample.passed
                        ? <CheckCircle2 className="h-4 w-4 text-[var(--status-healthy)]" />
                        : <XCircle className="h-4 w-4 text-[var(--status-offline)]" />}
                    </div>
                    <span className="w-20 text-center text-xs text-[var(--text-muted)]">{sample.latencyMs}ms</span>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-1)] p-12 text-center">
                <BarChart3 className="mx-auto h-8 w-8 text-[var(--text-subtle)] mb-3" />
                <p className="text-sm text-[var(--text-muted)]">
                  Sample results are available for completed tasks with detailed data. Try eval-001 or eval-002.
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        description={confirmState.description}
        confirmLabel={confirmState.confirmLabel}
        variant={confirmState.variant}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((prev) => ({ ...prev, open: false }))}
      />
    </div>
  )
}

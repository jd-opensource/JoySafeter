'use client'

import { motion } from 'framer-motion'
import {
  Clock,
  Play,
  CheckCircle2,
  XCircle,
  Plus,
  Bot,
  Database,
  BarChart3,
} from 'lucide-react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import CountUp from 'react-countup'

import { cn } from '@/lib/core/utils/cn'
import { evaluationStats, evaluationTasks, type EvalStatus } from '@/mocks/evaluations'

const statusConfig: Record<EvalStatus, { icon: React.ComponentType<{ className?: string }>; color: string; bg: string }> = {
  pending: { icon: Clock, color: 'text-[var(--status-pending)]', bg: 'bg-purple-50 dark:bg-purple-950/20' },
  running: { icon: Play, color: 'text-[var(--status-running)]', bg: 'bg-blue-50 dark:bg-blue-950/20' },
  completed: { icon: CheckCircle2, color: 'text-[var(--status-healthy)]', bg: 'bg-green-50 dark:bg-green-950/20' },
  failed: { icon: XCircle, color: 'text-[var(--status-offline)]', bg: 'bg-red-50 dark:bg-red-950/20' },
}

const statCardConfig = [
  { key: 'pending' as const, value: evaluationStats.pending, color: 'var(--status-pending)' },
  { key: 'running' as const, value: evaluationStats.running, color: 'var(--status-running)' },
  { key: 'completed' as const, value: evaluationStats.completed, color: 'var(--status-healthy)' },
  { key: 'failed' as const, value: evaluationStats.failed, color: 'var(--status-offline)' },
]

export default function EvaluatePage() {
  const { t } = useTranslation()

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">{t('evaluate.title')}</h1>
          <p className="mt-1 text-sm text-[var(--text-tertiary)]">{t('evaluate.subtitle')}</p>
        </div>
        <button className="flex items-center gap-2 rounded-lg bg-[var(--brand-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90">
          <Plus className="h-4 w-4" />
          {t('evaluate.newEvaluation')}
        </button>
      </div>

      {/* Stat Cards */}
      <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {statCardConfig.map((stat, i) => {
          const cfg = statusConfig[stat.key]
          const Icon = cfg.icon
          return (
            <motion.div
              key={stat.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              className={cn('rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4')}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--text-muted)] capitalize">{t(`evaluate.${stat.key}`)}</span>
                <Icon className={cn('h-4 w-4', cfg.color)} />
              </div>
              <div className="mt-2 text-2xl font-bold" style={{ color: stat.color }}>
                <CountUp end={stat.value} duration={1} />
              </div>
            </motion.div>
          )
        })}
      </div>

      {/* Tasks Table */}
      <h2 className="mb-3 text-sm font-semibold text-[var(--text-secondary)]">{t('evaluate.tasks')}</h2>
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden">
        {/* Header */}
        <div className="border-b border-[var(--border)] px-4 py-2.5 flex items-center text-[11px] font-medium text-[var(--text-muted)]">
          <span className="flex-1">Name</span>
          <span className="w-32">{t('evaluate.agent')}</span>
          <span className="w-28">{t('evaluate.dataset')}</span>
          <span className="w-24 text-center">{t('evaluate.progress')}</span>
          <span className="w-20 text-center">{t('evaluate.accuracy')}</span>
          <span className="w-20 text-center">Status</span>
        </div>

        {evaluationTasks.map((task, i) => {
          const cfg = statusConfig[task.status]
          const Icon = cfg.icon
          return (
            <Link key={task.id} href={`/evaluate/${task.id}`}>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.03 }}
                className={cn(
                  'flex items-center px-4 py-3 transition-colors hover:bg-[var(--surface-3)] cursor-pointer',
                  i < evaluationTasks.length - 1 && 'border-b border-[var(--border)]'
                )}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[var(--text-primary)] truncate">{task.name}</p>
                </div>
                <span className="w-32 flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                  <Bot className="h-3 w-3" /> {task.agentName}
                </span>
                <span className="w-28 flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                  <Database className="h-3 w-3" /> {task.dataset}
                </span>
                <div className="w-24 flex items-center justify-center gap-2">
                  <div className="h-1.5 w-16 rounded-full bg-[var(--surface-5)] overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${task.progress}%`, backgroundColor: task.status === 'failed' ? 'var(--status-offline)' : 'var(--brand-500)' }}
                    />
                  </div>
                  <span className="text-[10px] text-[var(--text-subtle)]">{task.progress}%</span>
                </div>
                <span className="w-20 text-center text-xs font-medium text-[var(--text-primary)]">
                  {task.accuracy !== null ? `${task.accuracy}%` : '—'}
                </span>
                <div className="w-20 flex items-center justify-center gap-1">
                  <Icon className={cn('h-3.5 w-3.5', cfg.color)} />
                  <span className={cn('text-[10px] font-medium capitalize', cfg.color)}>{task.status}</span>
                </div>
              </motion.div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}

'use client'

import { motion } from 'framer-motion'
import {
  Bot,
  Database,
  BarChart3,
  Terminal,
  ArrowRight,
  Activity,
  Rocket,
} from 'lucide-react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import CountUp from 'react-countup'

import { cn } from '@/lib/core/utils/cn'
import {
  dashboardStats,
  recentActivities,
  systemStatus,
  quickActions,
  type ActivityItem,
} from '@/mocks/dashboard'

const statCards = [
  { key: 'totalAgents' as const, icon: Bot, value: dashboardStats.totalAgents, suffix: '' },
  { key: 'knowledgeBases' as const, icon: Database, value: dashboardStats.knowledgeBases, suffix: '' },
  { key: 'evalCompletionRate' as const, icon: BarChart3, value: dashboardStats.evaluationCompletionRate, suffix: '%' },
  { key: 'activeContainers' as const, icon: Terminal, value: dashboardStats.activeContainers, suffix: '' },
]

const actionIcons = {
  bot: Bot,
  database: Database,
  chart: BarChart3,
  terminal: Terminal,
} as const

const activityIcons = {
  bot: Bot,
  chart: BarChart3,
  database: Database,
  rocket: Rocket,
  terminal: Terminal,
} as const

function formatTime(ts: string): string {
  const d = new Date(ts)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return 'Just now'
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'healthy'
      ? 'bg-[var(--status-healthy)]'
      : status === 'degraded'
        ? 'bg-[var(--status-degraded)]'
        : 'bg-[var(--status-offline)]'
  return (
    <span className={cn('inline-block h-2 w-2 rounded-full', color, status === 'degraded' && 'animate-pulse')} />
  )
}

export default function DashboardPage() {
  const { t } = useTranslation()

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">{t('dashboard.title')}</h1>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">{t('dashboard.subtitle')}</p>
      </div>

      {/* Stat Cards */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat, i) => {
          const Icon = stat.icon
          return (
            <motion.div
              key={stat.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.08, duration: 0.3 }}
              className="group rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 transition-shadow hover:-translate-y-0.5 hover:shadow-lg"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--text-muted)]">
                  {t(`dashboard.${stat.key}`)}
                </span>
                <Icon className="h-4 w-4 text-[var(--text-subtle)]" />
              </div>
              <div className="mt-3 text-3xl font-bold text-[var(--text-primary)]">
                <CountUp end={stat.value} duration={1.5} decimals={stat.suffix === '%' ? 1 : 0} />
                {stat.suffix}
              </div>
            </motion.div>
          )
        })}
      </div>

      {/* Quick Actions */}
      <div className="mb-8">
        <h2 className="mb-4 text-sm font-semibold text-[var(--text-secondary)]">
          {t('dashboard.quickActions')}
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {quickActions.map((action) => {
            const Icon = actionIcons[action.icon]
            return (
              <Link key={action.id} href={action.href}>
                <motion.div
                  whileHover={{ y: -2 }}
                  whileTap={{ scale: 0.97 }}
                  className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 transition-colors hover:border-[var(--brand-500)]"
                >
                  <Icon className="h-5 w-5 text-[var(--brand-500)]" />
                  <span className="text-sm font-medium text-[var(--text-primary)]">
                    {t(`dashboard.${action.id === 'create-agent' ? 'createAgent' : action.id === 'import-dataset' ? 'importDataset' : action.id === 'run-evaluation' ? 'runEvaluation' : 'startOpenClaw'}`)}
                  </span>
                  <ArrowRight className="ml-auto h-4 w-4 text-[var(--text-subtle)]" />
                </motion.div>
              </Link>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent Activity */}
        <div className="lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold text-[var(--text-secondary)]">
            {t('dashboard.recentActivity')}
          </h2>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)]">
            {recentActivities.map((activity, i) => {
              const Icon = activityIcons[activity.icon]
              return (
                <motion.div
                  key={activity.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={cn(
                    'flex items-start gap-3 px-4 py-3 transition-colors hover:bg-[var(--surface-3)]',
                    i < recentActivities.length - 1 && 'border-b border-[var(--border)]'
                  )}
                >
                  <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--surface-5)]">
                    <Icon className="h-3.5 w-3.5 text-[var(--text-tertiary)]" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--text-primary)]">{activity.title}</p>
                    <p className="mt-0.5 text-xs text-[var(--text-muted)] truncate">{activity.description}</p>
                  </div>
                  <span className="flex-shrink-0 text-xs text-[var(--text-subtle)]">{formatTime(activity.timestamp)}</span>
                </motion.div>
              )
            })}
          </div>
        </div>

        {/* System Status */}
        <div>
          <h2 className="mb-4 text-sm font-semibold text-[var(--text-secondary)]">
            {t('dashboard.systemStatus')}
          </h2>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4 space-y-3">
            {Object.entries(systemStatus).map(([key, status]) => (
              <div key={key} className="flex items-center justify-between">
                <span className="text-sm capitalize text-[var(--text-secondary)]">{key}</span>
                <div className="flex items-center gap-2">
                  <StatusDot status={status} />
                  <span className="text-xs text-[var(--text-muted)] capitalize">{t(`dashboard.${status}`)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

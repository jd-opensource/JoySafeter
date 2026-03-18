'use client'

import { motion } from 'framer-motion'
import {
  Activity,
  ArrowRight,
  BarChart3,
  Bot,
  Clock3,
  Database,
  ExternalLink,
  ShieldCheck,
  Terminal,
  TrendingUp,
  Zap,
} from 'lucide-react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import CountUp from 'react-countup'

import { cn } from '@/lib/core/utils/cn'
import { dashboardStats, quickActions, recentActivities, systemStatus } from '@/mocks/dashboard'

function formatTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return 'Just now'
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 24, filter: 'blur(8px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  transition: { duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] as const },
})

const activityIconMap = {
  bot: Bot,
  chart: BarChart3,
  database: Database,
  rocket: Zap,
  terminal: Terminal,
} as const

const actionIconMap = {
  bot: Bot,
  database: Database,
  terminal: Terminal,
} as const

const statusConfig = {
  healthy: { label: 'Operational', tone: 'bg-[rgba(53,111,97,0.08)] text-[var(--status-healthy)]', dot: 'bg-[var(--status-healthy)]' },
  degraded: { label: 'Monitoring', tone: 'bg-[rgba(155,106,45,0.1)] text-[var(--status-degraded)]', dot: 'bg-[var(--status-degraded)] status-pulse' },
  offline: { label: 'Offline', tone: 'bg-[rgba(156,68,56,0.1)] text-[var(--status-offline)]', dot: 'bg-[var(--status-offline)]' },
} as const

const summaryStats = [
  {
    label: 'Deployed agents',
    value: dashboardStats.totalAgents,
    icon: Bot,
    copy: 'Production-ready orchestrations under governance',
  },
  {
    label: 'Knowledge systems',
    value: dashboardStats.knowledgeBases,
    icon: Database,
    copy: 'Indexed intelligence domains available to every workflow',
  },
  {
    label: 'Operational uptime',
    value: 99.3,
    suffix: '%',
    icon: ShieldCheck,
    copy: 'Platform availability across the last reporting window',
  },
  {
    label: 'Active sandboxes',
    value: dashboardStats.activeContainers,
    icon: Terminal,
    copy: 'Running analysis environments with live supervision',
  },
]

function ExecutiveSummary() {
  const { t } = useTranslation()

  return (
    <motion.section {...fadeUp(0)} className="surface-panel relative overflow-hidden px-7 py-7">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--brand-indigo)] to-transparent" />
      <div className="flex flex-col gap-8 xl:flex-row xl:items-end xl:justify-between">
        <div className="max-w-2xl space-y-5">
          <div className="executive-kicker">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-500)]" />
            <span>Executive security overview</span>
          </div>
          <div className="space-y-4">
            <h1 className="font-display text-[clamp(2.5rem,5vw,4.6rem)] leading-[0.92] tracking-[-0.05em] text-[var(--text-primary)]">
              {t('dashboard.title')}
            </h1>
            <p className="max-w-xl text-[15px] leading-7 text-[var(--text-secondary)]">
              {t('dashboard.subtitle')}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <Link href="/build" className="btn-primary inline-flex items-center gap-2 rounded-full px-5 py-3 text-sm font-semibold">
            Build an Agent
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/evaluate"
            className="inline-flex items-center gap-2 rounded-full border border-[var(--border-strong)] bg-[rgba(255,255,255,0.54)] px-5 py-3 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--surface-elevated)]"
          >
            Review Evaluations
          </Link>
        </div>
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-4">
        {summaryStats.map(({ icon: Icon, label, value, suffix, copy }, index) => (
          <motion.div
            key={label}
            {...fadeUp(0.06 + index * 0.06)}
            className="surface-panel-flat px-5 py-5"
          >
            <div className="flex items-center justify-between">
              <div className="section-label">{label}</div>
              <div className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--brand-500)]">
                <Icon className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-5 metric-value">
              <CountUp end={value} duration={1.6} decimals={suffix ? 1 : 0} />
              {suffix && <span className="ml-1 text-[1.2rem] text-[var(--text-secondary)]">{suffix}</span>}
            </div>
            <p className="mt-3 text-[13px] leading-6 text-[var(--text-secondary)]">{copy}</p>
          </motion.div>
        ))}
      </div>
    </motion.section>
  )
}

function ActivityFeed() {
  return (
    <motion.section {...fadeUp(0.08)} className="surface-panel overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--divider)] px-6 py-5">
        <div>
          <div className="section-label">Recent activity</div>
          <h2 className="mt-2 text-[1.1rem] font-semibold text-[var(--text-primary)]">Operational narrative</h2>
        </div>
        <div className="quiet-badge">
          <Activity className="h-3.5 w-3.5" />
          {recentActivities.length} events
        </div>
      </div>

      <div className="divide-y divide-[var(--divider)]">
        {recentActivities.map((activity, index) => {
          const Icon = activityIconMap[activity.icon]

          return (
            <motion.div
              key={activity.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, delay: 0.08 + index * 0.04, ease: [0.22, 1, 0.36, 1] }}
              className="flex items-start gap-4 px-6 py-4 transition-colors hover:bg-[rgba(255,255,255,0.36)]"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--brand-500)]">
                <Icon className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-semibold leading-6 text-[var(--text-primary)]">{activity.title}</p>
                <p className="mt-1 text-[13px] leading-6 text-[var(--text-secondary)]">{activity.description}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--text-secondary)]">
                <Clock3 className="h-3.5 w-3.5" />
                {formatTime(activity.timestamp)}
              </div>
            </motion.div>
          )
        })}
      </div>
    </motion.section>
  )
}

function StatusPanel() {
  return (
    <motion.section {...fadeUp(0.12)} className="surface-panel px-6 py-6">
      <div className="section-label">System posture</div>
      <div className="mt-2 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-[var(--brand-500)]" />
        <h2 className="text-[1.05rem] font-semibold text-[var(--text-primary)]">Platform status summary</h2>
      </div>

      <div className="mt-6 space-y-3">
        {Object.entries(systemStatus).map(([key, status]) => {
          const config = statusConfig[status]
          return (
            <div key={key} className="flex items-center justify-between rounded-[14px] border border-[var(--divider)] bg-[rgba(255,255,255,0.4)] px-4 py-3">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]">{key}</div>
                <div className="mt-1 text-[13px] text-[var(--text-primary)]">Core service supervision</div>
              </div>
              <div className={cn('inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em]', config.tone)}>
                <span className={cn('h-2 w-2 rounded-full', config.dot)} />
                {config.label}
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-6 rounded-[16px] border border-[var(--divider)] bg-[var(--surface-2)] p-4">
        <div className="flex items-center justify-between">
          <div className="section-label">Momentum</div>
          <div className="quiet-badge">
            <TrendingUp className="h-3.5 w-3.5" />
            Weekly gain
          </div>
        </div>
        <div className="mt-4 text-[28px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">+14%</div>
        <p className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">
          Agent utilization and workflow throughput both improved against the previous reporting period.
        </p>
      </div>
    </motion.section>
  )
}

function QuickActionsPanel() {
  return (
    <motion.section {...fadeUp(0.16)} className="surface-panel px-6 py-6">
      <div className="section-label">Next actions</div>
      <h2 className="mt-2 text-[1.05rem] font-semibold text-[var(--text-primary)]">Move execution forward</h2>
      <div className="mt-5 grid gap-3">
        {quickActions.map((action) => {
          const Icon = actionIconMap[action.icon]
          return (
            <Link
              key={action.id}
              href={action.href}
              className="group flex items-center justify-between rounded-[16px] border border-[var(--divider)] bg-[rgba(255,255,255,0.45)] px-4 py-4 transition-all hover:border-[var(--border-strong)] hover:bg-[var(--surface-elevated)]"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--brand-500)]">
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-[13px] font-semibold text-[var(--text-primary)]">{action.label}</div>
                  <div className="mt-1 text-[12px] text-[var(--text-secondary)]">Open workspace surface</div>
                </div>
              </div>
              <ExternalLink className="h-4 w-4 text-[var(--text-secondary)] transition-transform group-hover:translate-x-0.5" />
            </Link>
          )
        })}
      </div>
    </motion.section>
  )
}

export default function DashboardPage() {
  return (
    <div className="executive-page">
      <div className="executive-page-content space-y-6">
        <ExecutiveSummary />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,0.7fr)]">
          <ActivityFeed />
          <div className="grid gap-6">
            <StatusPanel />
            <QuickActionsPanel />
          </div>
        </div>
      </div>
    </div>
  )
}

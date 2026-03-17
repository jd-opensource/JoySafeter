'use client'

import { motion } from 'framer-motion'
import {
  Bot,
  Database,
  BarChart3,
  Terminal,
  ArrowRight,
  Zap,
  ShieldCheck,
  TrendingUp,
  Clock,
  Activity,
  Sparkles,
  ExternalLink,
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

/* ── helpers ── */
function formatTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return 'Just now'
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const activityIconMap = {
  bot: Bot,
  chart: BarChart3,
  database: Database,
  rocket: Zap,
  terminal: Terminal,
} as const

const activityColorMap = {
  bot: 'text-violet-400 bg-violet-500/15',
  chart: 'text-emerald-400 bg-emerald-500/15',
  database: 'text-cyan-400 bg-cyan-500/15',
  rocket: 'text-amber-400 bg-amber-500/15',
  terminal: 'text-rose-400 bg-rose-500/15',
} as const

const statusConfig = {
  healthy: { label: 'Operational', color: 'text-emerald-400', dot: 'bg-emerald-400' },
  degraded: { label: 'Degraded', color: 'text-amber-400', dot: 'bg-amber-400 animate-pulse' },
  offline: { label: 'Offline', color: 'text-rose-400', dot: 'bg-rose-400' },
} as const

const EASE = [0.32, 0.72, 0, 1] as [number, number, number, number]

/* ── fade-up variant ── */
const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 20, filter: 'blur(6px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  transition: { duration: 0.5, delay, ease: EASE },
})

/* ── Components ── */

function HeroCard() {
  const { t } = useTranslation()
  return (
    <div className="relative overflow-hidden rounded-2xl bg-white/[0.04] border border-violet-500/20 p-6 flex flex-col justify-between min-h-[200px] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
      {/* Background glow orb */}
      <div className="absolute -right-12 -top-12 h-48 w-48 rounded-full bg-violet-600/20 blur-3xl pointer-events-none" />
      <div className="absolute -left-8 bottom-0 h-32 w-32 rounded-full bg-indigo-600/15 blur-3xl pointer-events-none" />

      <div className="relative">
        {/* Eyebrow */}
        <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1">
          <Sparkles className="h-3 w-3 text-violet-400" />
          <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-violet-300">
            AI Security Platform
          </span>
        </div>

        <h1 className="text-[22px] font-bold leading-tight text-white/90">
          {t('dashboard.title')}
        </h1>
        <p className="mt-1.5 text-[13px] text-white/45 leading-relaxed max-w-[280px]">
          {t('dashboard.subtitle')}
        </p>
      </div>

      <div className="relative flex items-center gap-3 mt-4">
        <Link
          href="/build"
          className="group inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-[13px] font-semibold text-white shadow-[0_0_16px_rgba(139,92,246,0.35)] transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] hover:shadow-[0_0_28px_rgba(139,92,246,0.5)] hover:-translate-y-0.5"
        >
          Build an Agent
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/15 transition-transform duration-200 group-hover:translate-x-0.5">
            <ArrowRight className="h-3 w-3" />
          </span>
        </Link>
        <Link
          href="/evaluate"
          className="inline-flex items-center gap-1.5 rounded-full border border-white/12 px-4 py-2 text-[13px] font-medium text-white/60 transition-all duration-200 hover:border-white/25 hover:text-white/80"
        >
          Run Evaluation
        </Link>
      </div>
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  suffix,
  trend,
  color,
  delay,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  suffix?: string
  trend?: string
  color: string
  delay: number
}) {
  return (
    <motion.div {...fadeUp(delay)} className="group relative overflow-hidden rounded-2xl bg-white/[0.04] border border-white/[0.07] p-5 transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] hover:border-violet-500/35 hover:-translate-y-1 hover:shadow-[0_0_32px_rgba(139,92,246,0.12)] shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-start justify-between">
        <div className={cn('flex h-9 w-9 items-center justify-center rounded-xl', color)}>
          <Icon className="h-4.5 w-4.5" />
        </div>
        {trend && (
          <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
            <TrendingUp className="h-3 w-3" />
            {trend}
          </span>
        )}
      </div>
      <div className="mt-4">
        <div className="text-[28px] font-bold tabular-nums text-white/90 leading-none">
          <CountUp end={value} duration={1.8} decimals={suffix === '%' ? 1 : 0} />
          {suffix && <span className="text-[18px] text-white/50 ml-0.5">{suffix}</span>}
        </div>
        <p className="mt-1.5 text-[12px] text-white/40">{label}</p>
      </div>
    </motion.div>
  )
}

function ActivityFeed() {
  return (
    <div className="rounded-2xl bg-white/[0.04] border border-white/[0.07] overflow-hidden shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-violet-400" />
          <span className="text-[13px] font-semibold text-white/80">Recent Activity</span>
        </div>
        <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] font-medium text-violet-300">
          {recentActivities.length} events
        </span>
      </div>

      <div className="divide-y divide-white/[0.05]">
        {recentActivities.map((activity, i) => {
          const Icon = activityIconMap[activity.icon]
          const colorClass = activityColorMap[activity.icon]
          return (
            <motion.div
              key={activity.id}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.1 + i * 0.04, duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
              className="group flex items-start gap-3 px-5 py-3.5 transition-colors duration-200 hover:bg-white/[0.03] cursor-default"
            >
              <div className={cn('mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg', colorClass)}>
                <Icon className="h-3.5 w-3.5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-medium text-white/80 leading-snug">{activity.title}</p>
                <p className="mt-0.5 text-[12px] text-white/35 truncate">{activity.description}</p>
              </div>
              <div className="flex-shrink-0 flex items-center gap-1 text-[11px] text-white/25">
                <Clock className="h-3 w-3" />
                {formatTime(activity.timestamp)}
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}

function SystemHealthCard() {
  return (
    <div className="rounded-2xl bg-white/[0.04] border border-white/[0.07] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-center gap-2 mb-4">
        <ShieldCheck className="h-4 w-4 text-emerald-400" />
        <span className="text-[13px] font-semibold text-white/80">System Health</span>
      </div>

      <div className="space-y-3">
        {Object.entries(systemStatus).map(([key, status]) => {
          const cfg = statusConfig[status]
          return (
            <div key={key} className="flex items-center justify-between">
              <span className="text-[13px] capitalize text-white/50">{key}</span>
              <div className="flex items-center gap-2">
                <span className={cn('h-1.5 w-1.5 rounded-full', cfg.dot)} />
                <span className={cn('text-[12px] font-medium', cfg.color)}>{cfg.label}</span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Mini uptime bar */}
      <div className="mt-5 pt-4 border-t border-white/[0.06]">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] text-white/35">Overall uptime</span>
          <span className="text-[12px] font-semibold text-emerald-400">99.3%</span>
        </div>
        <div className="flex gap-0.5">
          {Array.from({ length: 28 }).map((_, i) => (
            <div
              key={i}
              className={cn(
                'h-4 flex-1 rounded-[2px]',
                i === 14 || i === 22 ? 'bg-amber-400/60' : 'bg-emerald-400/50'
              )}
            />
          ))}
        </div>
        <p className="mt-1 text-[10px] text-white/25">Last 28 days</p>
      </div>
    </div>
  )
}

function QuickActionsCard() {
  const quickActionConfigs = [
    { href: '/build', label: 'New Agent', icon: Bot, color: 'from-violet-600/20 to-indigo-600/20 border-violet-500/25', iconColor: 'text-violet-400' },
    { href: '/knowledge/datasets', label: 'Import Data', icon: Database, color: 'from-cyan-600/20 to-sky-600/20 border-cyan-500/25', iconColor: 'text-cyan-400' },
    { href: '/evaluate', label: 'Evaluate', icon: BarChart3, color: 'from-emerald-600/20 to-teal-600/20 border-emerald-500/25', iconColor: 'text-emerald-400' },
    { href: '/openclaw', label: 'OpenClaw', icon: Terminal, color: 'from-rose-600/20 to-orange-600/20 border-rose-500/25', iconColor: 'text-rose-400' },
  ]

  return (
    <div className="rounded-2xl bg-white/[0.04] border border-white/[0.07] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-center gap-2 mb-4">
        <Zap className="h-4 w-4 text-amber-400" />
        <span className="text-[13px] font-semibold text-white/80">Quick Start</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {quickActionConfigs.map(({ href, label, icon: Icon, color, iconColor }) => (
          <Link key={href} href={href}>
            <motion.div
              whileHover={{ y: -2, scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
              transition={{ duration: 0.15, ease: [0.32, 0.72, 0, 1] }}
              className={cn(
                'flex flex-col items-start gap-2 rounded-xl bg-gradient-to-br p-3 border transition-all duration-200',
                'hover:shadow-[0_4px_20px_rgba(0,0,0,0.3)]',
                color
              )}
            >
              <div className={cn('flex h-7 w-7 items-center justify-center rounded-lg bg-white/10', iconColor)}>
                <Icon className="h-3.5 w-3.5" />
              </div>
              <div className="flex items-center justify-between w-full">
                <span className="text-[12px] font-semibold text-white/70">{label}</span>
                <ExternalLink className="h-3 w-3 text-white/25" />
              </div>
            </motion.div>
          </Link>
        ))}
      </div>
    </div>
  )
}

/* ── Main Page ── */
export default function DashboardPage() {
  const { t } = useTranslation()

  const stats = [
    {
      icon: Bot,
      label: t('dashboard.totalAgents'),
      value: dashboardStats.totalAgents,
      trend: '+3 this week',
      color: 'bg-violet-500/15 text-violet-400',
      delay: 0.05,
    },
    {
      icon: Database,
      label: t('dashboard.knowledgeBases'),
      value: dashboardStats.knowledgeBases,
      trend: '+1 today',
      color: 'bg-cyan-500/15 text-cyan-400',
      delay: 0.10,
    },
    {
      icon: BarChart3,
      label: t('dashboard.evalCompletionRate'),
      value: dashboardStats.evaluationCompletionRate,
      suffix: '%',
      color: 'bg-emerald-500/15 text-emerald-400',
      delay: 0.15,
    },
    {
      icon: Terminal,
      label: t('dashboard.activeContainers'),
      value: dashboardStats.activeContainers,
      color: 'bg-rose-500/15 text-rose-400',
      delay: 0.20,
    },
  ]

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      {/* ── Bento grid ── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:grid-rows-[auto_auto_auto]">

        {/* Row 1: Hero (col 1-7) + Activity (col 8-12, spans rows 1-3) */}
        <motion.div {...fadeUp(0)} className="lg:col-span-7">
          <HeroCard />
        </motion.div>

        {/* Activity feed — tall, spans 3 rows */}
        <motion.div {...fadeUp(0.08)} className="lg:col-span-5 lg:row-span-3">
          <ActivityFeed />
        </motion.div>

        {/* Stat cards row — 4 across the first 7 columns */}
        <div className="lg:col-span-7 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {stats.map((s) => (
            <StatCard key={s.label} {...s} />
          ))}
        </div>

        {/* Row 3: System health (col 1-4) + Quick actions (col 5-7) */}
        <motion.div {...fadeUp(0.18)} className="lg:col-span-4">
          <SystemHealthCard />
        </motion.div>

        <motion.div {...fadeUp(0.22)} className="lg:col-span-3">
          <QuickActionsCard />
        </motion.div>

      </div>
    </div>
  )
}

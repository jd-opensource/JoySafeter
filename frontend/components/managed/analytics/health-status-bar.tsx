'use client'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { formatPercent } from '@/lib/managed/analytics/formatters'
import type { HealthCheckResponse } from '@/lib/managed/analytics/types'
import { CheckCircle2, AlertTriangle, XCircle, Loader2 } from 'lucide-react'

interface HealthStatusBarProps {
  data: HealthCheckResponse | undefined
  loading?: boolean
}

const STATUS_CONFIG = {
  healthy: {
    icon: CheckCircle2,
    bg: 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800',
    iconColor: 'text-emerald-600 dark:text-emerald-400',
    textColor: 'text-emerald-800 dark:text-emerald-300',
  },
  warning: {
    icon: AlertTriangle,
    bg: 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800',
    iconColor: 'text-amber-600 dark:text-amber-400',
    textColor: 'text-amber-800 dark:text-amber-300',
  },
  critical: {
    icon: XCircle,
    bg: 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800',
    iconColor: 'text-red-600 dark:text-red-400',
    textColor: 'text-red-800 dark:text-red-300',
  },
}

function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '<1m'
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

export function HealthStatusBar({ data, loading }: HealthStatusBarProps) {
  const { t } = useTranslation()

  if (loading || !data) {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        <span className="text-sm text-muted-foreground">{t('common.loading')}</span>
      </div>
    )
  }

  const config = STATUS_CONFIG[data.status] || STATUS_CONFIG.healthy
  const StatusIcon = config.icon

  return (
    <div className={cn('mb-6 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border px-3 py-2.5', config.bg)}>
      <div className="flex items-center gap-2">
        <StatusIcon className={cn('h-4 w-4', config.iconColor)} />
        <span className={cn('text-sm font-medium', config.textColor)}>
          {t(`analytics.health.${data.status}`)}
        </span>
      </div>

      <div className="h-4 w-px bg-current opacity-20" />

      <span className="text-sm text-foreground">
        {t('analytics.health.successRate')} <strong>{formatPercent(data.success_rate)}</strong>
      </span>

      <div className="h-4 w-px bg-current opacity-20" />

      <span className="text-sm text-foreground">
        {data.running_tasks > 0
          ? t('analytics.health.runningTasks', { count: data.running_tasks })
          : t('analytics.health.noRunningTasks')}
      </span>

      <div className="h-4 w-px bg-current opacity-20" />

      <span className="text-sm text-foreground">
        {t('analytics.health.queueWait', { time: data.queue_wait.avg_sec > 60
          ? `${Math.round(data.queue_wait.avg_sec / 60)}m`
          : `${Math.round(data.queue_wait.avg_sec)}s`
        })}
      </span>

      <div className="h-4 w-px bg-current opacity-20" />

      <span className="text-sm text-muted-foreground">
        {data.last_error_at
          ? t('analytics.health.lastError', { time: formatRelativeTime(data.last_error_at) })
          : t('analytics.health.noErrors')}
      </span>
    </div>
  )
}

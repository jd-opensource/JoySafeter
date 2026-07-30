'use client'

import { AlertTriangle, XCircle, Info, ArrowRight, CheckCircle2 } from 'lucide-react'
import Link from 'next/link'

import { useTranslation } from '@/lib/i18n'
import { alertDetailKey } from '@/lib/managed/analytics/health-presenter'
import type { AlertItem, AlertConfig } from '@/lib/managed/analytics/types'
import { cn } from '@/lib/utils'

import { AlertConfigPanel } from './alert-config-panel'

interface AlertListProps {
  alerts: AlertItem[]
  loading?: boolean
  config: AlertConfig
  onConfigChange: (config: AlertConfig) => void
}

const SEVERITY_CONFIG = {
  error: {
    icon: XCircle,
    iconColor: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-50/50 dark:bg-red-950/20',
  },
  warning: {
    icon: AlertTriangle,
    iconColor: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-50/50 dark:bg-amber-950/20',
  },
  info: {
    icon: Info,
    iconColor: 'text-blue-600 dark:text-blue-400',
    bg: 'bg-blue-50/50 dark:bg-blue-950/20',
  },
}

export function AlertList({ alerts, loading, config, onConfigChange }: AlertListProps) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 h-4 w-32 animate-pulse rounded bg-muted" />
        <div className="space-y-2">
          <div className="h-10 animate-pulse rounded bg-muted" />
          <div className="h-10 animate-pulse rounded bg-muted" />
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-foreground">{t('analytics.alerts.title')}</h3>
        <AlertConfigPanel config={config} onChange={onConfigChange} />
      </div>

      {alerts.length === 0 ? (
        <div className="flex items-center gap-2 rounded-md bg-emerald-50/50 px-3 py-2.5 dark:bg-emerald-950/20">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          <span className="text-xs text-emerald-800 dark:text-emerald-300">
            {t('analytics.alerts.allClear')}
          </span>
        </div>
      ) : (
        <div className="max-h-[240px] space-y-1 overflow-y-auto">
          {alerts.map((alert, i) => {
            const config = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.info
            const Icon = config.icon
            return (
              <div
                key={`${alert.type}-${alert.agent_id ?? i}`}
                className={cn('flex items-start gap-1.5 rounded-md px-2 py-1.5', config.bg)}
              >
                <Icon className={cn('mt-px h-3.5 w-3.5 shrink-0', config.iconColor)} />
                <div className="min-w-0 flex-1">
                  {alert.agent_name && (
                    <p className="truncate text-xs font-medium text-foreground">
                      {alert.agent_name}
                    </p>
                  )}
                  <p className="line-clamp-1 text-xs text-muted-foreground">
                    {t(alertDetailKey(alert.type), alert.params)}
                  </p>
                </div>
                {alert.agent_id && (
                  <Link
                    href={`/managed/analytics/calls?agent_id=${alert.agent_id}`}
                    className="shrink-0 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

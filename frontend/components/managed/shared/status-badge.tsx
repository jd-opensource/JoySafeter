'use client'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'

type Status = 'active' | 'idle' | 'running' | 'terminated' | 'archived' | string

const statusConfig: Record<
  string,
  { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }
> = {
  active: {
    variant: 'outline',
    className: 'border-green-500/50 bg-green-500/10 text-green-700 dark:text-green-400',
  },
  running: {
    variant: 'outline',
    className: 'border-green-500/50 bg-green-500/10 text-green-700 dark:text-green-400',
  },
  idle: { variant: 'outline' },
  terminated: { variant: 'outline' },
  archived: { variant: 'outline' },
  private: { variant: 'outline' },
  passed: {
    variant: 'outline',
    className: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  },
  warning: {
    variant: 'outline',
    className: 'border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  },
  blocked: {
    variant: 'outline',
    className: 'border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400',
  },
  failed: {
    variant: 'outline',
    className: 'border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400',
  },
  not_scanned: {
    variant: 'outline',
    className: 'border-slate-400/50 bg-slate-400/10 text-slate-600 dark:text-slate-400',
  },
}

const defaultConfig = { variant: 'outline' as const }

const statusI18nKeys: Record<string, string> = {
  active: 'common.active',
  running: 'sessions.agentRunning',
  idle: 'common.idle',
  terminated: 'common.terminated',
  archived: 'common.archived',
  private: 'common.private',
  passed: 'common.passed',
  warning: 'common.warning',
  blocked: 'common.blocked',
  failed: 'common.failed',
  not_scanned: 'common.notScanned',
}

export function StatusBadge({ status }: { status: Status }) {
  const { t } = useTranslation()
  const normalized = status.toLowerCase()
  const config = statusConfig[normalized] || defaultConfig
  const i18nKey = statusI18nKeys[normalized]
  const label = i18nKey ? t(i18nKey) : status

  return (
    <Badge variant={config.variant} className={config.className || ''}>
      {label}
    </Badge>
  )
}

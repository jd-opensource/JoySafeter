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
}

const defaultConfig = { variant: 'outline' as const }

const statusI18nKeys: Record<string, string> = {
  active: 'common.active',
  running: 'sessions.agentRunning',
  idle: 'common.idle',
  terminated: 'common.terminated',
  archived: 'common.archived',
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

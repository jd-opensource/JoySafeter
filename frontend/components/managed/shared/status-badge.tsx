'use client'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'
import { statusBadgeClass } from '@/lib/managed/status-tone'

type Status = 'active' | 'idle' | 'running' | 'terminated' | 'archived' | string

const statusI18nKeys: Record<string, string> = {
  active: 'common.active',
  running: 'managed.sessions.agentRunning',
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

// Statuses rendered as a plain outline pill with no tone coloring.
const NEUTRAL_OUTLINE = new Set(['idle', 'terminated', 'archived', 'private', 'not_scanned'])

export function StatusBadge({ status }: { status: Status }) {
  const { t } = useTranslation()
  const normalized = status.toLowerCase()
  const i18nKey = statusI18nKeys[normalized]
  const label = i18nKey ? t(i18nKey) : status
  const className = NEUTRAL_OUTLINE.has(normalized) ? '' : statusBadgeClass(normalized)

  return (
    <Badge variant="outline" className={className}>
      {label}
    </Badge>
  )
}


'use client'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'
import type { ReleaseStatus } from '@/types/agent-release'

export function ReleaseStatusBadge({ status }: { status: ReleaseStatus }) {
  const { t } = useTranslation()
  switch (status) {
    case 'active':
      return (
        <Badge className="bg-green-600 text-white hover:bg-green-700">
          {t('agents.build.release.status.live', { defaultValue: 'Live' })}
        </Badge>
      )
    case 'superseded':
      return (
        <Badge variant="secondary">
          {t('agents.build.release.status.superseded', { defaultValue: 'Superseded' })}
        </Badge>
      )
    case 'ready':
      return (
        <Badge variant="outline">
          {t('agents.build.release.status.ready', { defaultValue: 'Ready' })}
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="destructive">
          {t('agents.build.release.status.failed', { defaultValue: 'Failed' })}
        </Badge>
      )
    case 'retired':
      return (
        <Badge variant="secondary" className="opacity-60">
          {t('agents.build.release.status.retired', { defaultValue: 'Archived' })}
        </Badge>
      )
  }
}

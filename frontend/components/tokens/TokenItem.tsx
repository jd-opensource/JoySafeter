'use client'

import { Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { PlatformToken } from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import { formatRelativeTime } from '@/lib/utils/formatRelativeTime'

interface TokenItemProps {
  token: PlatformToken
  onRevoke: (token: PlatformToken) => void
  isRevoking?: boolean
}

export function TokenItem({ token, onRevoke, isRevoking }: TokenItemProps) {
  const { t } = useTranslation()

  return (
    <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm transition-colors hover:bg-gray-50/50">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-gray-900">{token.name}</span>
          <span className="shrink-0 font-mono text-xs text-gray-400">{token.tokenPrefix}...</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {token.scopes.map((scope) => (
            <Badge
              key={scope}
              variant="outline"
              className="rounded-full border-indigo-200 bg-indigo-50 px-2 py-0 text-[10px] font-medium text-indigo-700"
            >
              {scope}
            </Badge>
          ))}
        </div>
        <div className="flex items-center gap-3 text-[11px] text-gray-400">
          <span>
            {t('settings.tokens.expiresAt')}:{' '}
            {token.expiresAt
              ? new Date(token.expiresAt).toLocaleDateString()
              : t('settings.tokens.noExpiry')}
          </span>
          <span className="h-3 w-px bg-gray-200" />
          <span>
            {t('settings.tokens.lastUsed')}: {formatRelativeTime(token.lastUsedAt, t)}
          </span>
        </div>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={() => onRevoke(token)}
        className="ml-4 h-8 w-8 shrink-0 text-gray-400 hover:bg-red-50 hover:text-red-600"
        disabled={isRevoking}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  )
}

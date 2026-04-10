'use client'

import { Check, Copy } from 'lucide-react'
import { useState, useCallback } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { UnifiedDialog } from '@/components/ui/unified-dialog'
import type { PlatformTokenCreateResponse } from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import { formatResourceType } from '@/lib/utils/formatResourceType'

interface TokenCreatedDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  tokenData: PlatformTokenCreateResponse | null
}

export function TokenCreatedDialog({ open, onOpenChange, tokenData }: TokenCreatedDialogProps) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    if (!tokenData?.token) return
    await navigator.clipboard.writeText(tokenData.token)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [tokenData?.token])

  return (
    <UnifiedDialog
      open={open}
      onOpenChange={onOpenChange}
      maxWidth="2xl"
      title={t('settings.tokens.tokenCreatedTitle')}
      description={t('settings.tokens.tokenCreatedMessage')}
      footer={
        <>
          <Button
            type="button"
            onClick={handleCopy}
            className="gap-2"
            disabled={!tokenData?.token}
          >
            {copied ? (
              <>
                <Check size={16} />
                {t('settings.tokens.copied')}
              </>
            ) : (
              <>
                <Copy size={16} />
                {t('settings.tokens.copyToken')}
              </>
            )}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t('settings.cancel')}
          </Button>
        </>
      }
    >
      <p className="text-sm text-[var(--status-warning)] bg-[var(--status-warning-bg)] rounded-lg px-4 py-3 border border-[var(--status-warning-border)]">
        {t('settings.tokens.tokenCreatedMessage')}
      </p>

      {tokenData && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-[var(--border-muted)]">
              <tr>
                <td className="px-4 py-3 font-medium text-[var(--text-secondary)] w-32">{t('settings.tokens.name')}</td>
                <td className="px-4 py-3 text-[var(--text-primary)]">{tokenData.name}</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">Key</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-[var(--text-secondary)] break-all select-all flex-1">
                      {tokenData.token}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={handleCopy}
                      className="h-8 w-8 shrink-0 text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
                      aria-label="Copy token"
                    >
                      {copied ? <Check size={15} className="text-[var(--status-success)]" /> : <Copy size={15} />}
                    </Button>
                  </div>
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.type')}</td>
                <td className="px-4 py-3 text-[var(--text-primary)]">{formatResourceType(tokenData.resourceType)}</td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.permissions')}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    {tokenData.scopes.map((scope) => (
                      <Badge
                        key={scope}
                        variant="outline"
                        className="rounded-full border-[var(--brand-200)] bg-[var(--brand-50)] px-2 py-0 text-2xs font-medium text-[var(--brand-700)]"
                      >
                        {scope}
                      </Badge>
                    ))}
                  </div>
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.createdAt')}</td>
                <td className="px-4 py-3 text-[var(--text-primary)]">
                  {tokenData.createdAt
                    ? new Date(tokenData.createdAt).toLocaleString()
                    : '-'}
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-[var(--text-secondary)]">{t('settings.tokens.expiresAt')}</td>
                <td className="px-4 py-3 text-[var(--text-primary)]">
                  {tokenData.expiresAt
                    ? new Date(tokenData.expiresAt).toLocaleString()
                    : t('settings.tokens.noExpiry')}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </UnifiedDialog>
  )
}

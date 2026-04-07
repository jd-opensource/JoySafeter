'use client'

import { Key, Loader2, Trash2, Copy, Check } from 'lucide-react'
import { useState } from 'react'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useCopyToClipboard } from '@/app/chat/shared/hooks/useCopyToClipboard'
import {
  usePlatformTokens,
  useRevokeToken,
  type PlatformToken,
  type TokenListParams,
} from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import { formatResourceType } from '@/lib/utils/formatResourceType'

interface TokenListProps {
  resourceType?: TokenListParams['resourceType']
  resourceId?: string
  header?: React.ReactNode
}

const getTypeBadgeColor = (type?: string | null) => {
  switch (type) {
    case 'workspace':
      return 'bg-purple-100 text-purple-700 hover:bg-purple-100/80 border-purple-200'
    case 'skill':
      return 'bg-blue-100 text-blue-700 hover:bg-blue-100/80 border-blue-200'
    case 'personal':
    default:
      return 'bg-[var(--surface-3)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)] border-[var(--border)]'
  }
}

function TokenTableRow({ token, onRevoke, revokingId }: { token: PlatformToken, onRevoke: (t: PlatformToken) => void, revokingId: string | null }) {
  const { t } = useTranslation()
  const { copied, handleCopy } = useCopyToClipboard()

  return (
    <TableRow>
      <TableCell className="font-medium text-[var(--text-primary)] border-b border-[var(--border-muted)]">
        {token.name}
      </TableCell>
      <TableCell className="border-b border-[var(--border-muted)]">
        <div className="flex items-center gap-2">
          <code className="bg-[var(--surface-1)] px-2 py-1 rounded text-xs text-[var(--text-secondary)] font-mono border border-[var(--border-muted)]">
            {token.tokenPrefix}...
          </code>
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  onClick={() => handleCopy(token.tokenPrefix)}
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('common.copy', { defaultValue: 'Copy' })}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </TableCell>
      <TableCell className="border-b border-[var(--border-muted)]">
        <Badge variant="outline" className={getTypeBadgeColor(token.resourceType)}>
          {formatResourceType(token.resourceType)}
        </Badge>
      </TableCell>
      <TableCell className="text-[var(--text-tertiary)] text-sm border-b border-[var(--border-muted)]">
        {token.createdAt ? new Date(token.createdAt).toLocaleDateString() : '-'}
      </TableCell>
      <TableCell className="text-[var(--text-tertiary)] text-sm border-b border-[var(--border-muted)]">
        {token.expiresAt ? new Date(token.expiresAt).toLocaleDateString() : t('settings.tokens.noExpiry', { defaultValue: 'No expiry' })}
      </TableCell>
      <TableCell className="text-right border-b border-[var(--border-muted)]">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onRevoke(token)}
          className="h-8 w-8 text-[var(--text-muted)] hover:bg-red-50 hover:text-red-600"
          disabled={revokingId === token.id}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </TableCell>
    </TableRow>
  )
}

export function TokenList({ resourceType, resourceId, header }: TokenListProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const params: TokenListParams | undefined =
    resourceType || resourceId ? { resourceType, resourceId } : undefined
  const { data: tokens, isLoading } = usePlatformTokens(params)
  const revokeToken = useRevokeToken()

  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false)
  const [tokenToRevoke, setTokenToRevoke] = useState<PlatformToken | null>(null)

  const openRevokeDialog = (token: PlatformToken) => {
    setTokenToRevoke(token)
    setRevokeDialogOpen(true)
  }

  const handleRevokeConfirm = async () => {
    if (!tokenToRevoke) return
    try {
      await revokeToken.mutateAsync(tokenToRevoke.id)
      toast({ title: t('settings.tokens.revokedSuccess') })
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error ? error.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    } finally {
      setRevokeDialogOpen(false)
      setTokenToRevoke(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full min-h-[200px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {header}

      {!tokens || tokens.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface-1)] py-12">
          <div className="rounded-full border border-[var(--border)] bg-[var(--surface-3)] p-4">
             <Key className="h-8 w-8 text-[var(--text-subtle)]" />
          </div>
          <p className="text-sm font-medium text-[var(--text-tertiary)]">{t('settings.tokens.emptyState')}</p>
        </div>
      ) : (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] shadow-sm">
          <Table>
            <TableHeader>
              <TableRow className="bg-[var(--surface-1)] hover:bg-[var(--surface-1)]">
                <TableHead className="w-[200px] text-[var(--text-secondary)] font-medium">{t('settings.tokens.name', { defaultValue: 'Name' })}</TableHead>
                <TableHead className="text-[var(--text-secondary)] font-medium">{t('settings.tokens.key', { defaultValue: 'Key' })}</TableHead>
                <TableHead className="text-[var(--text-secondary)] font-medium">{t('settings.tokens.type', { defaultValue: 'Type' })}</TableHead>
                <TableHead className="text-[var(--text-secondary)] font-medium">{t('settings.tokens.createdAt', { defaultValue: 'Created At' })}</TableHead>
                <TableHead className="text-[var(--text-secondary)] font-medium">{t('settings.tokens.expiresAt', { defaultValue: 'Expires At' })}</TableHead>
                <TableHead className="w-[80px] text-right text-[var(--text-secondary)] font-medium">{t('settings.tokens.actions', { defaultValue: 'Actions' })}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((token) => (
                <TokenTableRow
                  key={token.id}
                  token={token}
                  onRevoke={openRevokeDialog}
                  revokingId={revokeToken.isPending ? tokenToRevoke?.id ?? null : null}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ConfirmDialog
        open={revokeDialogOpen}
        onOpenChange={setRevokeDialogOpen}
        title={t('settings.tokens.revokeConfirmTitle')}
        description={t('settings.tokens.revokeConfirmMessage')}
        confirmLabel={t('settings.tokens.revoke')}
        cancelLabel={t('common.cancel')}
        variant="destructive"
        loading={revokeToken.isPending}
        onConfirm={handleRevokeConfirm}
      />
    </div>
  )
}

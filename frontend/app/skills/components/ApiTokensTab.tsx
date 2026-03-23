'use client'

import { Copy, Key, Plus, Trash2 } from 'lucide-react'
import React, { useMemo, useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import {
  usePlatformTokens,
  useCreateToken,
  useRevokeToken,
  type PlatformToken,
  type PlatformTokenCreateResponse,
} from '@/hooks/queries/platformTokens'
import { useCopyToClipboard } from '@/app/chat/shared/hooks/useCopyToClipboard'
import { useTranslation } from '@/lib/i18n'
import { formatRelativeTime } from '@/lib/utils/formatRelativeTime'

interface ApiTokensTabProps {
  skillId: string
}

export function ApiTokensTab({ skillId }: ApiTokensTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const { copied, handleCopy } = useCopyToClipboard()

  const [showCreateForm, setShowCreateForm] = useState(false)
  const [tokenName, setTokenName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; open: boolean }>({
    id: '',
    open: false,
  })
  const [createdToken, setCreatedToken] = useState<PlatformTokenCreateResponse | null>(null)

  const { data: tokens = [], isLoading } = usePlatformTokens()
  const createMutation = useCreateToken()
  const revokeMutation = useRevokeToken()

  const skillTokens = useMemo(
    () => tokens.filter((tok: PlatformToken) => tok.resourceType === 'skill' && tok.resourceId === skillId),
    [tokens, skillId],
  )

  const handleCreate = async () => {
    if (!tokenName.trim()) return
    try {
      const result = await createMutation.mutateAsync({
        name: tokenName.trim(),
        scopes: ['skill:execute'],
        resource_type: 'skill',
        resource_id: skillId,
      })
      setCreatedToken(result)
      toast({ title: t('settings.tokens.createdSuccess') })
      setTokenName('')
      setShowCreateForm(false)
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  const handleRevoke = async () => {
    try {
      await revokeMutation.mutateAsync(revokeTarget.id)
      toast({ title: t('settings.tokens.revokedSuccess') })
      setRevokeTarget({ id: '', open: false })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Create token button */}
      <div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="gap-2"
          disabled={skillTokens.length >= 50}
        >
          <Plus size={14} />
          {t('settings.tokens.create')}
        </Button>
        {skillTokens.length >= 50 && (
          <p className="mt-1 text-xs text-amber-600">{t('settings.tokens.limitReached')}</p>
        )}

        {showCreateForm && (
          <div className="mt-3 flex items-end gap-2 rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div className="flex-1">
              <Label className="text-xs">{t('settings.tokens.name')}</Label>
              <Input
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
                placeholder={t('settings.tokens.namePlaceholder')}
                className="mt-1"
              />
            </div>
            <Button size="sm" onClick={handleCreate} disabled={createMutation.isPending}>
              <Plus size={14} />
            </Button>
          </div>
        )}
      </div>

      {/* Token list */}
      {skillTokens.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <Key className="h-8 w-8 text-gray-300" />
          <p className="text-sm text-gray-500">{t('settings.tokens.emptyState')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {skillTokens.map((tok: PlatformToken) => (
            <div
              key={tok.id}
              className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{tok.name}</span>
                  <code className="rounded bg-gray-100 px-1 text-xs text-gray-500">
                    {tok.tokenPrefix}...
                  </code>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-gray-400">
                  <span>
                    {t('settings.tokens.lastUsed')}: {formatRelativeTime(tok.lastUsedAt, t)}
                  </span>
                  {tok.expiresAt && (
                    <span>
                      {t('settings.tokens.expiresAt')}:{' '}
                      {new Date(tok.expiresAt).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 text-xs text-red-500 hover:text-red-700"
                onClick={() => setRevokeTarget({ id: tok.id, open: true })}
              >
                <Trash2 size={12} />
                {t('settings.tokens.revoke')}
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Revoke confirm dialog */}
      <AlertDialog
        open={revokeTarget.open}
        onOpenChange={(open) => setRevokeTarget((prev) => ({ ...prev, open }))}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.tokens.revokeConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings.tokens.revokeConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevoke}
              className="bg-red-600 text-white hover:bg-red-700"
            >
              {t('settings.tokens.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Token created dialog - shows the raw token once */}
      <Dialog open={!!createdToken} onOpenChange={(open) => !open && setCreatedToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('settings.tokens.tokenCreatedTitle')}</DialogTitle>
            <DialogDescription>{t('settings.tokens.tokenCreatedMessage')}</DialogDescription>
          </DialogHeader>
          {createdToken && (
            <div className="py-4">
              <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
                <code className="flex-1 break-all text-sm">{createdToken.token}</code>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0 gap-1"
                  onClick={() => handleCopy(createdToken.token)}
                >
                  <Copy size={14} />
                  {copied ? t('settings.tokens.copied') : t('settings.tokens.copyToken')}
                </Button>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setCreatedToken(null)}>{t('common.close') || 'Close'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

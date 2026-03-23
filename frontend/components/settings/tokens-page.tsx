'use client'

import { Key, Loader2, Trash2 } from 'lucide-react'
import { useState } from 'react'

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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import { usePlatformTokens, useCreateToken, useRevokeToken } from '@/hooks/queries/platformTokens'
import type { PlatformToken, PlatformTokenCreateResponse } from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'

import { CreateTokenDialog } from './create-token-dialog'
import { TokenCreatedDialog } from './token-created-dialog'

function formatRelativeTime(dateStr: string | null, t: (key: string, opts?: any) => string): string {
  if (!dateStr) return t('settings.tokens.neverUsed')
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('settings.tokens.justNow')
  if (mins < 60) return t('settings.tokens.minutesAgo', { count: mins })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('settings.tokens.hoursAgo', { count: hours })
  const days = Math.floor(hours / 24)
  return t('settings.tokens.daysAgo', { count: days })
}

export const TokensPage = () => {
  const { t } = useTranslation()
  const { toast } = useToast()

  const { data: tokens, isLoading } = usePlatformTokens()
  const createToken = useCreateToken()
  const revokeToken = useRevokeToken()

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [tokenCreatedDialogOpen, setTokenCreatedDialogOpen] = useState(false)
  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false)
  const [tokenToRevoke, setTokenToRevoke] = useState<PlatformToken | null>(null)

  const handleCreateSubmit = async (data: {
    name: string
    scopes: string[]
    expires_at?: string | null
  }) => {
    try {
      const response: PlatformTokenCreateResponse = await createToken.mutateAsync(data)
      setCreatedToken(response.token)
      setCreateDialogOpen(false)
      setTokenCreatedDialogOpen(true)
      toast({
        title: t('settings.tokens.createdSuccess'),
      })
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error ? error.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleRevokeConfirm = async () => {
    if (!tokenToRevoke) return
    try {
      await revokeToken.mutateAsync(tokenToRevoke.id)
      toast({
        title: t('settings.tokens.revokedSuccess'),
      })
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

  const openRevokeDialog = (token: PlatformToken) => {
    setTokenToRevoke(token)
    setRevokeDialogOpen(true)
  }

  if (isLoading) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  const activeTokens = (tokens ?? []).filter((tok) => tok.isActive)

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 p-2 shadow-sm">
            <Key className="h-5 w-5 text-white" />
          </div>
          <div>
            <h2 className="text-lg font-bold tracking-tight text-gray-900">
              {t('settings.tokens.title')}
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">{t('settings.tokens.description')}</p>
          </div>
        </div>
        <Button
          size="sm"
          onClick={() => setCreateDialogOpen(true)}
          disabled={activeTokens.length >= 50}
          className="gap-2 rounded-lg"
        >
          <Key className="h-3.5 w-3.5" />
          <span className="text-xs font-medium">
            {activeTokens.length >= 50
              ? t('settings.tokens.limitReached')
              : t('settings.tokens.create')}
          </span>
        </Button>
      </div>

      {/* Token List */}
      <div className="flex-1 overflow-auto">
        {activeTokens.length === 0 ? (
          <div className="flex h-full min-h-[300px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-200 bg-gray-50/50">
            <div className="rounded-full border border-gray-200 bg-gray-100 p-4">
              <Key className="h-8 w-8 text-gray-300" />
            </div>
            <p className="text-sm font-medium text-gray-500">{t('settings.tokens.emptyState')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {activeTokens.map((token) => (
              <div
                key={token.id}
                className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm transition-colors hover:bg-gray-50/50"
              >
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-gray-900">
                      {token.name}
                    </span>
                    <span className="shrink-0 font-mono text-xs text-gray-400">
                      {token.tokenPrefix}...
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {token.scopes.map((scope) => (
                      <Badge
                        key={scope}
                        variant="outline"
                        className="rounded-full border-indigo-200 bg-indigo-50 px-2 py-0 text-[10px] font-medium text-indigo-700"
                      >
                        {scope.replace('skills:', '')}
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
                      {t('settings.tokens.lastUsed')}:{' '}
                      {formatRelativeTime(token.lastUsedAt, t)}
                    </span>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => openRevokeDialog(token)}
                  className="ml-4 h-8 w-8 shrink-0 text-gray-400 hover:bg-red-50 hover:text-red-600"
                  disabled={revokeToken.isPending}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Token Dialog */}
      <CreateTokenDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onSubmit={handleCreateSubmit}
        isPending={createToken.isPending}
      />

      {/* Token Created Dialog */}
      <TokenCreatedDialog
        open={tokenCreatedDialogOpen}
        onOpenChange={setTokenCreatedDialogOpen}
        token={createdToken}
      />

      {/* Revoke Confirm Dialog */}
      <AlertDialog open={revokeDialogOpen} onOpenChange={setRevokeDialogOpen}>
        <AlertDialogContent className="rounded-xl border-0 shadow-xl">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold">
              {t('settings.tokens.revokeConfirmTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-gray-500">
              {t('settings.tokens.revokeConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="rounded-lg">
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevokeConfirm}
              className="rounded-lg bg-red-600 text-white hover:bg-red-700"
            >
              {revokeToken.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('settings.tokens.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

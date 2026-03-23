'use client'

import { Key, Loader2 } from 'lucide-react'
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
import { useToast } from '@/components/ui/use-toast'
import {
  usePlatformTokens,
  useRevokeToken,
  type PlatformToken,
  type TokenListParams,
} from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'

import { TokenItem } from './TokenItem'

interface TokenListProps {
  /** Filter tokens by resource type (server-side) */
  resourceType?: TokenListParams['resourceType']
  /** Filter tokens by resource ID (server-side) */
  resourceId?: string
  /** Additional content rendered above the list (e.g. create button) */
  header?: React.ReactNode
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

  const activeTokens = (tokens ?? []).filter((tok) => tok.isActive)

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
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {header}

      {activeTokens.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-200 bg-gray-50/50 py-12">
          <div className="rounded-full border border-gray-200 bg-gray-100 p-4">
            <Key className="h-8 w-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-500">{t('settings.tokens.emptyState')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {activeTokens.map((token) => (
            <TokenItem
              key={token.id}
              token={token}
              onRevoke={openRevokeDialog}
              isRevoking={revokeToken.isPending}
            />
          ))}
        </div>
      )}

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
            <AlertDialogCancel className="rounded-lg">{t('common.cancel')}</AlertDialogCancel>
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

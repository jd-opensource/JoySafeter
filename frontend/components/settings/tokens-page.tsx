'use client'

import { Key } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import { TokenList } from '@/components/tokens/TokenList'
import { usePlatformTokens, useCreateToken } from '@/hooks/queries/platformTokens'
import type { PlatformTokenCreateResponse } from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'

import { CreateTokenDialog } from './create-token-dialog'
import { TokenCreatedDialog } from './token-created-dialog'

export const TokensPage = () => {
  const { t } = useTranslation()
  const { toast } = useToast()

  const { data: tokens } = usePlatformTokens()
  const createToken = useCreateToken()

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [tokenCreatedDialogOpen, setTokenCreatedDialogOpen] = useState(false)

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
      toast({ title: t('settings.tokens.createdSuccess') })
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error ? error.message : t('common.operationFailed'),
        variant: 'destructive',
      })
    }
  }

  const headerContent = (
    <div className="flex items-center justify-between">
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
        disabled={(tokens?.length ?? 0) >= 50}
        className="gap-2 rounded-lg"
      >
        <Key className="h-3.5 w-3.5" />
        <span className="text-xs font-medium">
          {(tokens?.length ?? 0) >= 50 ? t('settings.tokens.limitReached') : t('settings.tokens.create')}
        </span>
      </Button>
    </div>
  )

  return (
    <div className="flex h-full flex-col">
      <TokenList header={headerContent} />

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
    </div>
  )
}

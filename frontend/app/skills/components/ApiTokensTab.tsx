'use client'

import { Copy, Plus } from 'lucide-react'
import { useState } from 'react'

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
import { TokenList } from '@/components/tokens/TokenList'
import {
  useCreateToken,
  usePlatformTokens,
  type PlatformTokenCreateResponse,
} from '@/hooks/queries/platformTokens'
import { useCopyToClipboard } from '@/app/chat/shared/hooks/useCopyToClipboard'
import { useTranslation } from '@/lib/i18n'

interface ApiTokensTabProps {
  skillId: string
}

export function ApiTokensTab({ skillId }: ApiTokensTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const { copied, handleCopy } = useCopyToClipboard()

  const [showCreateForm, setShowCreateForm] = useState(false)
  const [tokenName, setTokenName] = useState('')
  const [createdToken, setCreatedToken] = useState<PlatformTokenCreateResponse | null>(null)

  // Server-side filtering: only fetch tokens bound to this skill
  const { data: tokens = [] } = usePlatformTokens({ resourceType: 'skill', resourceId: skillId })
  const createMutation = useCreateToken()

  const activeCount = tokens.filter((tok) => tok.isActive).length

  const handleCreate = async () => {
    if (!tokenName.trim()) return
    try {
      const result = await createMutation.mutateAsync({
        name: tokenName.trim(),
        scopes: ['skills:execute'],
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

  const headerContent = (
    <div>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setShowCreateForm(!showCreateForm)}
        className="gap-2"
        disabled={activeCount >= 50}
      >
        <Plus size={14} />
        {t('settings.tokens.create')}
      </Button>
      {activeCount >= 50 && (
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
  )

  return (
    <div className="flex flex-col gap-4 p-4">
      <TokenList resourceType="skill" resourceId={skillId} header={headerContent} />

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

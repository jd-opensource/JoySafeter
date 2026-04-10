'use client'

import { Plus } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { TokenList } from '@/components/tokens/TokenList'
import { TokenCreatedDialog } from '@/components/settings/token-created-dialog'
import {
  useCreateToken,
  usePlatformTokens,
  type PlatformTokenCreateResponse,
} from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface ApiTokensTabProps {
  skillId: string
}

export function ApiTokensTab({ skillId }: ApiTokensTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showCreateForm, setShowCreateForm] = useState(false)
  const [tokenName, setTokenName] = useState('')
  const [tokenScope, setTokenScope] = useState('skills:execute')
  const [createdToken, setCreatedToken] = useState<PlatformTokenCreateResponse | null>(null)

  const { data: tokens = [] } = usePlatformTokens({ resourceType: 'skill', resourceId: skillId })
  const createMutation = useCreateToken()

  const handleCreate = async () => {
    if (!tokenName.trim()) return
    try {
      const result = await createMutation.mutateAsync({
        name: tokenName.trim(),
        scopes: [tokenScope],
        resource_type: 'skill',
        resource_id: skillId,
      })
      setCreatedToken(result)
      toast({ title: t('settings.tokens.createdSuccess') })
      setTokenName('')
      setShowCreateForm(false)
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
  }

  const headerContent = (
    <div>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setShowCreateForm(!showCreateForm)}
        className="gap-2"
        disabled={tokens.length >= 50}
      >
        <Plus size={14} />
        {t('settings.tokens.create')}
      </Button>
      {tokens.length >= 50 && (
        <p className="mt-1 text-xs text-[var(--status-warning)]">{t('settings.tokens.limitReached')}</p>
      )}

      {showCreateForm && (
        <div className="mt-3 flex items-end gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-4">
          <div className="flex-1">
            <Label className="text-xs">{t('settings.tokens.name')}</Label>
            <Input
              value={tokenName}
              onChange={(e) => setTokenName(e.target.value)}
              placeholder={t('settings.tokens.namePlaceholder')}
              className="mt-1"
            />
          </div>
          <div className="w-32">
            <Label className="text-xs">{t('settings.tokens.role', { defaultValue: 'Role' })}</Label>
            <Select value={tokenScope} onValueChange={setTokenScope}>
              <SelectTrigger className="mt-1 bg-[var(--surface-elevated)]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="skills:execute">
                  {t('settings.tokens.roles.executor', { defaultValue: 'Executor' })}
                </SelectItem>
                <SelectItem value="skills:read">
                  {t('settings.tokens.roles.viewer', { defaultValue: 'Viewer' })}
                </SelectItem>
                <SelectItem value="skills:admin">
                  {t('settings.tokens.roles.admin', { defaultValue: 'Admin' })}
                </SelectItem>
              </SelectContent>
            </Select>
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

      <TokenCreatedDialog
        open={!!createdToken}
        onOpenChange={(open) => !open && setCreatedToken(null)}
        tokenData={createdToken}
      />
    </div>
  )
}

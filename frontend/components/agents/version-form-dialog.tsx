'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useCreateVersion } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'

type DefinitionKind = 'prompt' | 'graph' | 'code' | 'hybrid'

interface VersionFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string
  workspaceId: string
}

export function VersionFormDialog({
  open,
  onOpenChange,
  agentId,
  workspaceId,
}: VersionFormDialogProps) {
  const { t } = useTranslation()
  const createVersion = useCreateVersion()

  const [definitionKind, setDefinitionKind] = useState<DefinitionKind>('prompt')
  const [changelog, setChangelog] = useState('')

  function resetForm() {
    setDefinitionKind('prompt')
    setChangelog('')
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()

    createVersion.mutate(
      {
        agentId,
        workspaceId,
        definition_kind: definitionKind,
        changelog: changelog.trim() || undefined,
      },
      {
        onSuccess: () => {
          resetForm()
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('agents.detail.createVersion')}</DialogTitle>
          <DialogDescription>{t('agents.detail.selectDefinitionKind')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>{t('agents.buildMethod')} *</Label>
            <Select
              value={definitionKind}
              onValueChange={(v) => setDefinitionKind(v as DefinitionKind)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="prompt">{t('agents.prompt.label')}</SelectItem>
                <SelectItem value="graph">{t('agents.graph.label')}</SelectItem>
                <SelectItem value="code">{t('agents.code.label')}</SelectItem>
                <SelectItem value="hybrid" disabled>{t('agents.hybrid.label')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>{t('agents.detail.changelog')}</Label>
            <Textarea
              value={changelog}
              onChange={(e) => setChangelog(e.target.value)}
              placeholder={t('agents.detail.changelogPlaceholder')}
              rows={3}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('agents.cancel')}
            </Button>
            <Button type="submit" disabled={createVersion.isPending}>
              {createVersion.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  {t('agents.detail.creatingVersion')}
                </>
              ) : (
                t('agents.detail.createVersion')
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

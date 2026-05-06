'use client'

import { Loader2 } from 'lucide-react'
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
import type { EngineKind } from '@/types/agent'

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

  const [engineKind, setEngineKind] = useState<EngineKind>('langgraph_visual')
  const [changelog, setChangelog] = useState('')

  function resetForm() {
    setEngineKind('langgraph_visual')
    setChangelog('')
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      resetForm()
    }
    onOpenChange(nextOpen)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()

    createVersion.mutate(
      {
        agentId,
        workspaceId,
        engine_kind: engineKind,
        changelog: changelog.trim() || undefined,
      },
      {
        onSuccess: () => {
          handleOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('agents.detail.createVersion')}</DialogTitle>
          <DialogDescription>{t('agents.detail.selectDefinitionKind')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>{t('agents.buildMethod')} *</Label>
            <Select value={engineKind} onValueChange={(v) => setEngineKind(v as EngineKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="langgraph_visual">{t('agents.graph.label')}</SelectItem>
                <SelectItem value="langgraph_code">{t('agents.code.label')}</SelectItem>
                <SelectItem value="claude_code">{t('agents.claudeCode.label')}</SelectItem>
                <SelectItem value="codex">{t('agents.codex.label')}</SelectItem>
                <SelectItem value="openclaw">{t('agents.openclaw.label')}</SelectItem>
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
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
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

'use client'

import { useState, useEffect } from 'react'

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
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { Agent, CreateAgentRequest } from '@/types/agent'

interface AgentFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent?: Agent | null
  workspaceId: string
  onSubmit: (data: CreateAgentRequest) => void
  isPending?: boolean
}

export function AgentFormDialog({
  open,
  onOpenChange,
  agent,
  workspaceId,
  onSubmit,
  isPending,
}: AgentFormDialogProps) {
  const { t } = useTranslation()
  const isEdit = Boolean(agent)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (open) {
      if (agent) {
        setName(agent.name)
        setDescription(agent.description || '')
      } else {
        setName('')
        setDescription('')
      }
    }
  }, [open, agent])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return

    onSubmit({
      name: name.trim(),
      description: description.trim() || undefined,
      definition_kind: 'prompt',
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? t('agents.editAgent') : t('agents.newAgent')}</DialogTitle>
          <DialogDescription>
            {isEdit ? t('agents.editAgentDescription') : t('agents.newAgentDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="agent-name">{t('agents.name')} *</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('agents.namePlaceholder')}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-description">{t('agents.description')}</Label>
            <Textarea
              id="agent-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('agents.descriptionPlaceholder')}
              rows={3}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!name.trim() || isPending}>
              {isPending
                ? isEdit
                  ? t('agents.saving')
                  : t('agents.creating')
                : isEdit
                  ? t('agents.save')
                  : t('agents.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

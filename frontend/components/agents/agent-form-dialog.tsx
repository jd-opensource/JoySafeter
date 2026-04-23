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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { Agent, CreateAgentRequest } from '@/types/agent'

type DefinitionKind = 'prompt' | 'graph' | 'code' | 'hybrid'

interface AgentFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent?: Agent | null
  workspaceId: string
  onSubmit: (data: CreateAgentRequest) => void
  isPending?: boolean
}

interface DefinitionKindOption {
  value: DefinitionKind
  labelKey: string
  descriptionKey: string
  disabled?: boolean
}

const DEFINITION_KIND_OPTIONS: DefinitionKindOption[] = [
  {
    value: 'prompt',
    labelKey: 'agents.prompt.label',
    descriptionKey: 'agents.prompt.description',
  },
  {
    value: 'graph',
    labelKey: 'agents.graph.label',
    descriptionKey: 'agents.graph.description',
  },
  {
    value: 'code',
    labelKey: 'agents.code.label',
    descriptionKey: 'agents.code.description',
    disabled: true,
  },
  {
    value: 'hybrid',
    labelKey: 'agents.hybrid.label',
    descriptionKey: 'agents.hybrid.description',
    disabled: true,
  },
]

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
  const [avatar, setAvatar] = useState('')
  const [definitionKind, setDefinitionKind] = useState<DefinitionKind>('prompt')

  useEffect(() => {
    if (open) {
      if (agent) {
        setName(agent.name)
        setDescription(agent.description || '')
        setAvatar(agent.avatar || '')
      } else {
        setName('')
        setDescription('')
        setAvatar('')
        setDefinitionKind('prompt')
      }
    }
  }, [open, agent])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return

    onSubmit({
      name: name.trim(),
      description: description.trim() || undefined,
      avatar: avatar.trim() || undefined,
      definition_kind: definitionKind,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
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
              rows={2}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-avatar">{t('agents.avatar')}</Label>
            <Input
              id="agent-avatar"
              value={avatar}
              onChange={(e) => setAvatar(e.target.value)}
              placeholder={t('agents.avatarPlaceholder')}
            />
          </div>

          {!isEdit && (
            <div className="space-y-2">
              <Label htmlFor="agent-definition-kind">{t('agents.buildMethod')}</Label>
              <Select
                value={definitionKind}
                onValueChange={(v) => setDefinitionKind(v as DefinitionKind)}
              >
                <SelectTrigger id="agent-definition-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEFINITION_KIND_OPTIONS.map((opt) => (
                    <SelectItem
                      key={opt.value}
                      value={opt.value}
                      textValue={t(opt.labelKey)}
                      disabled={opt.disabled}
                    >
                      <div>
                        <span>{t(opt.labelKey)}</span>
                        <span className="ml-2 text-xs text-[var(--text-muted)]">
                          {t(opt.descriptionKey)}
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

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

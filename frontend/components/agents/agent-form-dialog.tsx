'use client'

import { Bot, Code2, GitBranch, Terminal } from 'lucide-react'
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
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import type { CreateAgentRequest, EngineKind } from '@/types/agent'

interface BuildMethodOption {
  value: EngineKind
  labelKey: string
  descriptionKey: string
  icon: React.ComponentType<{ className?: string }>
}

const BUILD_METHOD_OPTIONS: BuildMethodOption[] = [
  {
    value: 'langgraph_visual',
    labelKey: 'agents.graph.label',
    descriptionKey: 'agents.graph.description',
    icon: GitBranch,
  },
  {
    value: 'langgraph_code',
    labelKey: 'agents.code.label',
    descriptionKey: 'agents.code.description',
    icon: Code2,
  },
  {
    value: 'claude_code',
    labelKey: 'agents.claudeCode.label',
    descriptionKey: 'agents.claudeCode.description',
    icon: Terminal,
  },
  {
    value: 'codex',
    labelKey: 'agents.codex.label',
    descriptionKey: 'agents.codex.description',
    icon: Bot,
  },
  {
    value: 'openclaw',
    labelKey: 'agents.openclaw.label',
    descriptionKey: 'agents.openclaw.description',
    icon: Terminal,
  },
]

interface CreateAgentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (data: CreateAgentRequest) => void
  isPending?: boolean
}

export function CreateAgentDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
}: CreateAgentDialogProps) {
  const { t } = useTranslation()

  const [name, setName] = useState('')
  const [engineKind, setEngineKind] = useState<EngineKind>('langgraph_visual')

  function resetForm() {
    setName('')
    setEngineKind('langgraph_visual')
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      resetForm()
    }
    onOpenChange(nextOpen)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return

    onSubmit({
      name: name.trim(),
      engine_kind: engineKind,
    })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('agents.newAgent', { defaultValue: 'New Agent' })}</DialogTitle>
          <DialogDescription>
            {t('agents.newAgentDescription', {
              defaultValue: 'Choose a name and build method to get started.',
            })}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="agent-name">{t('agents.name', { defaultValue: 'Name' })} *</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('agents.namePlaceholder', {
                defaultValue: 'Give your agent a name',
              })}
              autoFocus
              required
            />
          </div>

          <div className="space-y-2">
            <Label>
              {t('agents.buildMethod', { defaultValue: 'Build method' })}
            </Label>
            <div className="grid gap-2" role="radiogroup" aria-label={t('agents.buildMethod', { defaultValue: 'Build method' })}>
              {BUILD_METHOD_OPTIONS.map((option) => {
                const Icon = option.icon
                const isSelected = engineKind === option.value
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    className={cn(
                      'flex items-center gap-3 rounded-lg border p-3 text-left transition-colors',
                      'hover:bg-[var(--surface-2)]',
                      isSelected
                        ? 'border-[var(--skill-brand-600)] bg-[var(--skill-brand-50)]'
                        : 'border-[var(--border)]',
                    )}
                    onClick={() => setEngineKind(option.value)}
                  >
                    <div
                      className={cn(
                        'flex h-8 w-8 shrink-0 items-center justify-center rounded-md',
                        isSelected
                          ? 'bg-[var(--skill-brand-600)] text-white'
                          : 'bg-[var(--surface-2)] text-[var(--text-muted)]',
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--text-primary)]">
                        {t(option.labelKey)}
                      </p>
                      <p className="text-xs text-[var(--text-muted)]">
                        {t(option.descriptionKey)}
                      </p>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button type="submit" disabled={!name.trim() || isPending}>
              {isPending
                ? t('common.creating', { defaultValue: 'Creating...' })
                : t('common.create', { defaultValue: 'Create' })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

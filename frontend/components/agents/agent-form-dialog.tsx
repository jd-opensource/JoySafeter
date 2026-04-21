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

const DEFINITION_KIND_LABELS: Record<DefinitionKind, string> = {
  prompt: 'Prompt',
  graph: 'Graph',
  code: 'Code',
  hybrid: 'Hybrid',
}

const DEFINITION_KIND_OPTIONS: DefinitionKind[] = ['prompt', 'graph', 'code', 'hybrid']

export function AgentFormDialog({
  open,
  onOpenChange,
  agent,
  workspaceId,
  onSubmit,
  isPending,
}: AgentFormDialogProps) {
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
          <DialogTitle>{isEdit ? 'Edit Agent' : 'New Agent'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'Update the agent details.'
              : 'Create a new AI agent for your workspace.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="agent-name">Name *</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Security Auditor"
              required
            />
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="agent-description">Description</Label>
            <Textarea
              id="agent-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this agent do?"
              rows={2}
            />
          </div>

          {/* Avatar URL */}
          <div className="space-y-2">
            <Label htmlFor="agent-avatar">Avatar URL</Label>
            <Input
              id="agent-avatar"
              value={avatar}
              onChange={(e) => setAvatar(e.target.value)}
              placeholder="https://..."
            />
          </div>

          {/* Definition Kind (only for create) */}
          {!isEdit && (
            <div className="space-y-2">
              <Label htmlFor="agent-definition-kind">Definition Kind</Label>
              <Select
                value={definitionKind}
                onValueChange={(v) => setDefinitionKind(v as DefinitionKind)}
              >
                <SelectTrigger id="agent-definition-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEFINITION_KIND_OPTIONS.map((dk) => (
                    <SelectItem key={dk} value={dk}>
                      {DEFINITION_KIND_LABELS[dk]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || isPending}>
              {isPending ? (isEdit ? 'Saving...' : 'Creating...') : isEdit ? 'Save' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

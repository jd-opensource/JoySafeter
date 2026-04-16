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
import type { AgentProfile, CreateAgentRequest, RuntimeType } from '@/types/agents'
import { RUNTIME_TYPE_LABELS } from '@/types/agents'

interface AgentFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent?: AgentProfile | null
  workspaceId: string
  onSubmit: (data: CreateAgentRequest) => void
  isPending?: boolean
}

const RUNTIME_OPTIONS: RuntimeType[] = ['claude_code', 'codex', 'openclaw', 'langgraph']

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
  const [runtimeType, setRuntimeType] = useState<RuntimeType>('claude_code')
  const [instructions, setInstructions] = useState('')
  const [maxConcurrentTasks, setMaxConcurrentTasks] = useState(1)
  const [skillIdsText, setSkillIdsText] = useState('')

  useEffect(() => {
    if (open) {
      if (agent) {
        setName(agent.name)
        setDescription(agent.description || '')
        setRuntimeType(agent.runtime_type)
        setInstructions(agent.instructions || '')
        setMaxConcurrentTasks(agent.max_concurrent_tasks)
        setSkillIdsText(agent.skill_ids?.join(', ') || '')
      } else {
        setName('')
        setDescription('')
        setRuntimeType('claude_code')
        setInstructions('')
        setMaxConcurrentTasks(1)
        setSkillIdsText('')
      }
    }
  }, [open, agent])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return

    const skillIds = skillIdsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    onSubmit({
      workspace_id: workspaceId,
      name: name.trim(),
      runtime_type: runtimeType,
      description: description.trim() || undefined,
      instructions: instructions.trim() || undefined,
      max_concurrent_tasks: maxConcurrentTasks,
      skill_ids: skillIds.length > 0 ? skillIds : undefined,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Agent' : 'New Agent'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'Update the agent configuration.'
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

          {/* Runtime Type */}
          <div className="space-y-2">
            <Label htmlFor="agent-runtime">Runtime Type</Label>
            <Select value={runtimeType} onValueChange={(v) => setRuntimeType(v as RuntimeType)}>
              <SelectTrigger id="agent-runtime">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RUNTIME_OPTIONS.map((rt) => (
                  <SelectItem key={rt} value={rt}>
                    {RUNTIME_TYPE_LABELS[rt]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Instructions */}
          <div className="space-y-2">
            <Label htmlFor="agent-instructions">Instructions</Label>
            <Textarea
              id="agent-instructions"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Custom instructions for the agent..."
              rows={3}
            />
          </div>

          {/* Max Concurrent Tasks */}
          <div className="space-y-2">
            <Label htmlFor="agent-max-tasks">Max Concurrent Tasks</Label>
            <Input
              id="agent-max-tasks"
              type="number"
              min={1}
              max={10}
              value={maxConcurrentTasks}
              onChange={(e) => setMaxConcurrentTasks(Number(e.target.value) || 1)}
            />
          </div>

          {/* Skill IDs */}
          <div className="space-y-2">
            <Label htmlFor="agent-skills">Skill IDs (comma-separated)</Label>
            <Input
              id="agent-skills"
              value={skillIdsText}
              onChange={(e) => setSkillIdsText(e.target.value)}
              placeholder="skill-1, skill-2"
            />
          </div>

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

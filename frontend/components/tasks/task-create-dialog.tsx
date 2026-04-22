'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
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
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useCreateTask } from '@/hooks/queries/tasks'
import type { MissionPriority } from '@/types/missions'
import { MISSION_PRIORITY_LABELS } from '@/types/missions'

interface TaskCreateDialogProps {
  workspaceId: string
  trigger: React.ReactNode
}

const PRIORITIES = Object.entries(MISSION_PRIORITY_LABELS) as [MissionPriority, string][]

export function TaskCreateDialog({ workspaceId, trigger }: TaskCreateDialogProps) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [objective, setObjective] = useState('')
  const [priority, setPriority] = useState<MissionPriority>('none')
  const [tagsInput, setTagsInput] = useState('')
  const [autoApprove, setAutoApprove] = useState(false)

  const createTask = useCreateTask()

  function reset() {
    setTitle('')
    setDescription('')
    setObjective('')
    setPriority('none')
    setTagsInput('')
    setAutoApprove(false)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)

    try {
      await createTask.mutateAsync({
        workspace_id: workspaceId,
        title: title.trim(),
        description: description.trim() || undefined,
        objective: objective.trim() || undefined,
        priority,
        tags: tags.length > 0 ? tags : undefined,
        auto_approve: autoApprove,
      })
      reset()
      setOpen(false)
    } catch {
      // Global mutation error handler shows toast
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New Task</DialogTitle>
            <DialogDescription>Create a new task for your team or agents.</DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="task-title">Title</Label>
              <Input
                id="task-title"
                placeholder="e.g. Scan target.apk for OWASP Top 10"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-description">Description</Label>
              <Textarea
                id="task-description"
                placeholder="Describe what this task involves..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-objective">Objective</Label>
              <Textarea
                id="task-objective"
                placeholder="Success criteria for this task..."
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-priority">Priority</Label>
              <Select value={priority} onValueChange={(v) => setPriority(v as MissionPriority)}>
                <SelectTrigger id="task-priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITIES.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-tags">Tags</Label>
              <Input
                id="task-tags"
                placeholder="security, mobile, audit (comma-separated)"
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="task-auto-approve">Auto Approve</Label>
                <p className="text-xs text-[var(--text-muted)]">
                  Skip human review — auto-approve tool calls and mark done on completion
                </p>
              </div>
              <Switch
                id="task-auto-approve"
                checked={autoApprove}
                onCheckedChange={setAutoApprove}
              />
            </div>
          </div>

          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!title.trim() || createTask.isPending}>
              {createTask.isPending ? 'Creating...' : 'Create Task'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

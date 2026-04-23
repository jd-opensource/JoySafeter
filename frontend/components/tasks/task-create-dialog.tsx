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
import { useAgents } from '@/hooks/queries/agents'
import { useCreateTask, useAssignTask } from '@/hooks/queries/tasks'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import type { TaskPriority } from '@/types/tasks'

const PRIORITY_KEYS: { value: TaskPriority; key: string }[] = [
  { value: 'none', key: 'tasks.priorityNone' },
  { value: 'low', key: 'tasks.priorityLow' },
  { value: 'medium', key: 'tasks.priorityMedium' },
  { value: 'high', key: 'tasks.priorityHigh' },
  { value: 'urgent', key: 'tasks.priorityUrgent' },
]

interface TaskCreateDialogProps {
  workspaceId: string
  defaultAgentId?: string
  trigger: React.ReactNode
}

export function TaskCreateDialog({ workspaceId, defaultAgentId, trigger }: TaskCreateDialogProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [goal, setGoal] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('none')
  const [agentId, setAgentId] = useState(defaultAgentId || '')
  const [tagsInput, setTagsInput] = useState('')
  const [autoApprove, setAutoApprove] = useState(false)

  const { data: agents = [] } = useAgents(workspaceId)
  const createTask = useCreateTask()
  const assignTask = useAssignTask()

  function reset() {
    setTitle('')
    setDescription('')
    setGoal('')
    setPriority('none')
    setAgentId(defaultAgentId || '')
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
      const task = await createTask.mutateAsync({
        workspace_id: workspaceId,
        title: title.trim(),
        description: description.trim() || undefined,
        goal: goal.trim() || undefined,
        priority,
        tags: tags.length > 0 ? tags : undefined,
        auto_approve: autoApprove,
      })

      if (agentId && task?.id) {
        try {
          await assignTask.mutateAsync({
            taskId: task.id,
            workspaceId,
            agentId: agentId,
          })
        } catch {
          // Task created but assignment failed — user can assign later
        }
      }

      reset()
      setOpen(false)
    } catch {
      // Global mutation error handler shows toast
    }
  }

  const isPending = createTask.isPending || assignTask.isPending

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>{t('tasks.createTitle')}</DialogTitle>
            <DialogDescription>{t('tasks.createDescription')}</DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="task-title">{t('tasks.taskTitleLabel')}</Label>
              <Input
                id="task-title"
                placeholder={t('tasks.taskTitlePlaceholder')}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-agent">{t('tasks.assignAgentLabel')}</Label>
              <Select value={agentId} onValueChange={setAgentId}>
                <SelectTrigger id="task-agent">
                  <SelectValue placeholder={t('tasks.assignAgentPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">{t('tasks.noAssignment')}</SelectItem>
                  {agents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-goal">{t('tasks.goalLabel')}</Label>
              <Textarea
                id="task-goal"
                placeholder={t('tasks.goalPlaceholder')}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-description">{t('tasks.descriptionLabel')}</Label>
              <Textarea
                id="task-description"
                placeholder={t('tasks.descriptionPlaceholder')}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="task-priority">{t('tasks.priorityLabel')}</Label>
                <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
                  <SelectTrigger id="task-priority">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PRIORITY_KEYS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {t(opt.key)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="task-tags">{t('tasks.tagsLabel')}</Label>
                <Input
                  id="task-tags"
                  placeholder={t('tasks.tagsPlaceholder')}
                  value={tagsInput}
                  onChange={(e) => setTagsInput(e.target.value)}
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="task-auto-approve">{t('tasks.autoApproveLabel')}</Label>
                <p className="text-xs text-[var(--text-muted)]">
                  {t('tasks.autoApproveHint')}
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
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!title.trim() || isPending}>
              {isPending ? t('tasks.creating') : t('tasks.createTask')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

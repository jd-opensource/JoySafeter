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
import type { TaskPriority } from '@/types/tasks'

const PRIORITY_OPTIONS: { value: TaskPriority; label: string }[] = [
  { value: 'none', label: '无' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'urgent', label: '紧急' },
]

interface TaskCreateDialogProps {
  workspaceId: string
  defaultAgentId?: string
  trigger: React.ReactNode
}

export function TaskCreateDialog({ workspaceId, defaultAgentId, trigger }: TaskCreateDialogProps) {
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
            <DialogTitle>新建任务</DialogTitle>
            <DialogDescription>创建一个新任务，分配给助手执行。</DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="task-title">任务标题</Label>
              <Input
                id="task-title"
                placeholder="例如：分析本季度销售数据"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-agent">分配助手</Label>
              <Select value={agentId} onValueChange={setAgentId}>
                <SelectTrigger id="task-agent">
                  <SelectValue placeholder="选择一个助手（可选）" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">不分配</SelectItem>
                  {agents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-goal">目标</Label>
              <Textarea
                id="task-goal"
                placeholder="任务的成功标准..."
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                rows={2}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-description">详细描述</Label>
              <Textarea
                id="task-description"
                placeholder="补充说明（可选）"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="task-priority">优先级</Label>
                <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
                  <SelectTrigger id="task-priority">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PRIORITY_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="task-tags">标签</Label>
                <Input
                  id="task-tags"
                  placeholder="用逗号分隔"
                  value={tagsInput}
                  onChange={(e) => setTagsInput(e.target.value)}
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="task-auto-approve">自动审批</Label>
                <p className="text-xs text-[var(--text-muted)]">
                  跳过人工审核，自动批准工具调用
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
              取消
            </Button>
            <Button type="submit" disabled={!title.trim() || isPending}>
              {isPending ? '创建中...' : '创建任务'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

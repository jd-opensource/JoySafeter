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

const DEFINITION_KIND_OPTIONS: { value: DefinitionKind; label: string; description: string }[] = [
  { value: 'prompt', label: '提示词配置', description: '通过系统提示词和指令定义助手行为' },
  { value: 'graph', label: '可视化编排', description: '通过拖拽节点构建工作流' },
  { value: 'code', label: '代码定义', description: '通过代码定义助手逻辑（即将推出）' },
  { value: 'hybrid', label: '混合模式', description: '组合多种定义方式（即将推出）' },
]

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
          <DialogTitle>{isEdit ? '编辑助手' : '新建助手'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? '修改助手的基本信息。'
              : '创建一个新的 AI 助手。'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="agent-name">名称 *</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：数据分析助手"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-description">描述</Label>
            <Textarea
              id="agent-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="这个助手负责做什么？"
              rows={2}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-avatar">头像 URL</Label>
            <Input
              id="agent-avatar"
              value={avatar}
              onChange={(e) => setAvatar(e.target.value)}
              placeholder="https://..."
            />
          </div>

          {!isEdit && (
            <div className="space-y-2">
              <Label htmlFor="agent-definition-kind">构建方式</Label>
              <Select
                value={definitionKind}
                onValueChange={(v) => setDefinitionKind(v as DefinitionKind)}
              >
                <SelectTrigger id="agent-definition-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEFINITION_KIND_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      <div>
                        <span>{opt.label}</span>
                        <span className="ml-2 text-xs text-[var(--text-muted)]">{opt.description}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="submit" disabled={!name.trim() || isPending}>
              {isPending ? (isEdit ? '保存中...' : '创建中...') : isEdit ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

'use client'

import { Loader2, MessageSquare, Pencil, Play, Plus, Rocket } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useAgent } from '@/hooks/queries/agents'
import { useAgentRuns, useCreateAgentRun } from '@/hooks/queries/agentRuns'
import { useReleases } from '@/hooks/queries/agentReleases'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useTasks } from '@/hooks/queries/tasks'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { RUN_STATUS_STYLES } from '@/types/agent-run'

const RUN_STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  succeeded: '已成功',
  failed: '失败',
  cancelled: '已取消',
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  return `${days}天前`
}

const TASK_STATUS_LABELS: Record<string, string> = {
  backlog: '待处理',
  todo: '待执行',
  in_progress: '进行中',
  in_review: '需检查',
  done: '已完成',
  cancelled: '已取消',
}

export default function AgentDetailPage() {
  const params = useParams()
  const router = useRouter()
  const agentId = params.agentId as string

  const [runDialogOpen, setRunDialogOpen] = useState(false)
  const [runPrompt, setRunPrompt] = useState('')

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)

  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: draftVersion } = useVersion(agentId, draftVersionId, workspaceId, {
    enabled: Boolean(draftVersionId),
  })

  const { data: releases = [] } = useReleases(agentId, workspaceId, {
    enabled: Boolean(workspaceId),
  })
  const releaseIds = new Set(releases.map((r) => r.id))

  const createRun = useCreateAgentRun()

  const { data: allRuns = [] } = useAgentRuns(
    { workspace_id: workspaceId },
    { enabled: Boolean(workspaceId) },
  )
  const recentRuns = allRuns.filter((run) => releaseIds.has(run.release_id)).slice(0, 5)

  const { data: allTasks = [] } = useTasks(workspaceId)
  const agentTasks = allTasks
    .filter((t) => (t.agent_id ?? t.assignee_id) === agentId)
    .slice(0, 4)

  if (!agent) return null

  const hasActiveRelease = Boolean(agent.active_release_id)

  async function handleRunNow() {
    if (!hasActiveRelease || !agent?.active_release_id) return
    setRunDialogOpen(true)
  }

  async function handleRunSubmit() {
    if (!agent?.active_release_id) return
    try {
      const run = await createRun.mutateAsync({
        release_id: agent.active_release_id,
        trigger_source: 'api',
        goal: runPrompt.trim() || undefined,
      })
      setRunDialogOpen(false)
      setRunPrompt('')
      if (run?.id) {
        router.push(`/agents/${agentId}/runs/${run.id}`)
      }
    } catch {
      // Global error handler shows toast
    }
  }

  return (
    <div className="space-y-8 px-8 py-6">
      {/* Description */}
      <div>
        <p className="text-sm text-[var(--text-secondary)]">
          {agent.description || '暂无描述'}
        </p>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card className="flex cursor-pointer flex-col items-center gap-2 border-[var(--border)] bg-[var(--surface-1)] p-6 transition-shadow hover:shadow-md">
          <Link href={`/agents/${agentId}/threads`} className="flex flex-col items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--brand-50)]">
              <MessageSquare className="h-5 w-5 text-[var(--brand-500)]" />
            </div>
            <span className="text-sm font-medium text-[var(--text-primary)]">开始对话</span>
          </Link>
        </Card>

        <Card
          className={`flex flex-col items-center gap-2 border-[var(--border)] bg-[var(--surface-1)] p-6 transition-shadow ${hasActiveRelease ? 'cursor-pointer hover:shadow-md' : 'opacity-50'}`}
          onClick={hasActiveRelease ? handleRunNow : undefined}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--status-success-bg)]">
            <Play className="h-5 w-5 text-[var(--status-success)]" />
          </div>
          <span className="text-sm font-medium text-[var(--text-primary)]">立即运行</span>
          {!hasActiveRelease && (
            <span className="text-xs text-[var(--text-muted)]">需要先发布</span>
          )}
        </Card>

        <Card className="flex cursor-pointer flex-col items-center gap-2 border-[var(--border)] bg-[var(--surface-1)] p-6 transition-shadow hover:shadow-md">
          <Link href={`/tasks?agent=${agentId}`} className="flex flex-col items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--status-warning-bg)]">
              <Plus className="h-5 w-5 text-[var(--status-warning)]" />
            </div>
            <span className="text-sm font-medium text-[var(--text-primary)]">分配任务</span>
          </Link>
        </Card>
      </div>

      {/* Current Draft + Active Release */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">当前草稿</h2>
            <Button variant="outline" size="sm" asChild>
              <Link href={`/agents/${agentId}/build`}>
                <Pencil className="mr-1.5 h-3.5 w-3.5" />
                编辑
              </Link>
            </Button>
          </div>
          {draftVersion ? (
            <div className="mt-3 flex items-center gap-3 text-sm text-[var(--text-muted)]">
              <Badge variant="outline">{draftVersion.definition_kind === 'graph' ? '可视化编排' : draftVersion.definition_kind === 'prompt' ? '提示词配置' : draftVersion.definition_kind}</Badge>
              <span>v{draftVersion.version_number}</span>
              <Badge variant="secondary">{draftVersion.status === 'frozen' ? '已冻结' : '草稿'}</Badge>
            </div>
          ) : (
            <p className="mt-3 text-sm text-[var(--text-muted)]">还没有草稿</p>
          )}
        </Card>

        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">发布状态</h2>
            <Button variant="outline" size="sm" asChild>
              <Link href={`/agents/${agentId}/build?tab=publish`}>
                <Rocket className="mr-1.5 h-3.5 w-3.5" />
                管理
              </Link>
            </Button>
          </div>
          {hasActiveRelease ? (
            <div className="mt-3 flex items-center gap-2 text-sm text-[var(--status-success)]">
              <div className="h-2 w-2 rounded-full bg-[var(--status-success)]" />
              已发布，可以运行
            </div>
          ) : (
            <p className="mt-3 text-sm text-[var(--text-muted)]">未发布</p>
          )}
        </Card>
      </div>

      {/* Recent Tasks */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">最近任务</h2>
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/tasks?agent=${agentId}`}>查看全部 →</Link>
          </Button>
        </div>
        {agentTasks.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">暂无任务</p>
        ) : (
          <div className="space-y-2">
            {agentTasks.map((task) => (
              <Link
                key={task.id}
                href={`/tasks?task=${task.id}`}
                className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-colors hover:bg-[var(--surface-3)]"
              >
                <span className="truncate text-sm text-[var(--text-primary)]">{task.title}</span>
                <Badge variant="outline" className="ml-2 flex-shrink-0 text-xs">
                  {TASK_STATUS_LABELS[task.status] || task.status}
                </Badge>
              </Link>
            ))}
          </div>
        )}
      </Card>

      {/* Recent Runs */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">最近运行</h2>
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/agents/${agentId}/runs`}>查看全部 →</Link>
          </Button>
        </div>
        {recentRuns.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">暂无运行记录</p>
        ) : (
          <div className="space-y-2">
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href={`/agents/${agentId}/runs/${run.id}`}
                className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-colors hover:bg-[var(--surface-3)]"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={RUN_STATUS_STYLES[run.status]}>
                    {RUN_STATUS_LABELS[run.status] || run.status}
                  </Badge>
                  {run.goal && (
                    <span className="truncate text-sm text-[var(--text-primary)]">{run.goal}</span>
                  )}
                </div>
                <span className="flex-shrink-0 text-xs text-[var(--text-muted)]">
                  {run.started_at ? formatRelativeTime(run.started_at) : '-'}
                </span>
              </Link>
            ))}
          </div>
        )}
      </Card>

      {/* Run Now Dialog */}
      <Dialog open={runDialogOpen} onOpenChange={setRunDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>立即运行</DialogTitle>
            <DialogDescription>输入运行指令（可选），助手将立即开始执行。</DialogDescription>
          </DialogHeader>
          <Textarea
            value={runPrompt}
            onChange={(e) => setRunPrompt(e.target.value)}
            placeholder="输入运行指令，例如：分析最近一周的数据..."
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRunDialogOpen(false)}>取消</Button>
            <Button onClick={handleRunSubmit} disabled={createRun.isPending}>
              {createRun.isPending ? <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />运行中...</> : '开始运行'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

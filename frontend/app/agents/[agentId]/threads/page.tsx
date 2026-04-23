'use client'

import { Loader2, MessageSquare, Plus } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useThreads, useCreateThread } from '@/hooks/queries/threads'
import { useWorkspaces } from '@/hooks/queries/workspaces'

export default function AgentThreadsPage() {
  const params = useParams()
  const router = useRouter()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: threads = [], isLoading } = useThreads(agentId, workspaceId)
  const createMutation = useCreateThread()

  const handleCreateThread = async () => {
    try {
      const newThread = await createMutation.mutateAsync({
        agent_id: agentId,
        workspace_id: workspaceId,
      })
      router.push(`/agents/${agentId}/threads/${newThread.id}`)
    } catch (error) {
      console.error('Failed to create thread:', error)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-8 py-6 text-sm text-[var(--text-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        加载中...
      </div>
    )
  }

  const THREAD_STATUS_LABELS: Record<string, string> = {
    active: '进行中',
    closed: '已结束',
    archived: '已归档',
  }

  return (
    <div className="space-y-4 px-8 py-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">对话</h2>
        <Button
          onClick={handleCreateThread}
          disabled={createMutation.isPending}
          className="gap-2"
        >
          {createMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
          新建对话
        </Button>
      </div>

      {threads.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <MessageSquare className="mb-3 h-12 w-12 text-[var(--text-muted)]" />
          <p className="text-sm text-[var(--text-muted)]">还没有对话</p>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            创建一个对话，开始与助手交流。
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {threads.map((thread) => (
            <Card
              key={thread.id}
              className="cursor-pointer border-[var(--border)] bg-[var(--surface-1)] p-4 transition-colors hover:bg-[var(--surface-2)]"
              onClick={() => router.push(`/agents/${agentId}/threads/${thread.id}`)}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <MessageSquare className="h-4 w-4 text-[var(--text-muted)]" />
                  <span className="text-sm font-medium text-[var(--text-primary)]">
                    {thread.title || '未命名对话'}
                  </span>
                  <Badge variant={thread.status === 'active' ? 'default' : 'secondary'}>
                    {THREAD_STATUS_LABELS[thread.status] || thread.status}
                  </Badge>
                </div>
                <span className="text-xs text-[var(--text-muted)]">
                  {new Date(thread.created_at).toLocaleDateString()}
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

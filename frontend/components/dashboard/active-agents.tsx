'use client'

import { Bot, ChevronRight } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo } from 'react'

import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'
import type { Task } from '@/types/tasks'

interface ActiveAgentsProps {
  workspaceId: string
  agents: Agent[]
  tasks: Task[]
}

export function ActiveAgents({ workspaceId, agents, tasks }: ActiveAgentsProps) {
  const { t } = useTranslation()
  const router = useRouter()

  const activeTaskCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    tasks.forEach((task: Task) => {
      const agentId = task.agent_id
      if (agentId && task.status === 'in_progress') {
        counts[agentId] = (counts[agentId] || 0) + 1
      }
    })
    return counts
  }, [tasks])

  return (
    <Card className="border-[var(--border)] bg-[var(--surface-elevated)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-[var(--text-muted)]" />
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('dashboard.activeAgents')}
          </h2>
        </div>
        <button
          type="button"
          className="flex items-center gap-1 text-xs text-[var(--brand-500)] hover:underline"
          onClick={() => router.push('/agents')}
        >
          {t('dashboard.viewAll')}
          <ChevronRight className="h-3 w-3" />
        </button>
      </div>

      {agents.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">{t('tasks.noTasks')}</p>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {agents.map((agent: Agent) => {
            const taskCount = activeTaskCounts[agent.id] || 0
            const isIdle = taskCount === 0

            return (
              <button
                key={agent.id}
                type="button"
                className={`flex shrink-0 items-center gap-3 rounded-xl border border-[var(--border)] px-4 py-3 transition-colors hover:bg-[var(--surface-3)] ${
                  isIdle ? 'opacity-50' : 'bg-[var(--surface-1)]'
                }`}
                onClick={() => router.push(`/agents/${agent.id}`)}
              >
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-lg text-xs font-semibold ${
                    isIdle
                      ? 'bg-[var(--surface-3)] text-[var(--text-muted)]'
                      : 'bg-[var(--skill-brand-50)] text-[var(--skill-brand-600)]'
                  }`}
                >
                  {agent.name.charAt(0).toUpperCase()}
                </div>
                <div className="text-left">
                  <p className="text-sm font-medium text-[var(--text-primary)]">{agent.name}</p>
                  <p className="text-xs text-[var(--text-muted)]">
                    {isIdle ? t('dashboard.idle') : `${taskCount} active`}
                  </p>
                </div>
              </button>
            )
          })}
        </div>
      )}
    </Card>
  )
}

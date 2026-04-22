'use client'

import { Kanban, List, Loader2, Plus, Target } from 'lucide-react'
import { useSearchParams, useRouter, useParams } from 'next/navigation'
import { useCallback, useState } from 'react'

import { TaskBoard } from '@/components/tasks/task-board'
import { TaskCreateDialog } from '@/components/tasks/task-create-dialog'
import { TaskDetailPanel } from '@/components/tasks/task-detail-panel'
import { TaskListView } from '@/components/tasks/task-list-view'
import { Button } from '@/components/ui/button'
import { useAgentNameMap } from '@/hooks/queries/agents'
import { useTasks } from '@/hooks/queries/tasks'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { cn } from '@/lib/utils'

type ViewMode = 'board' | 'list'

export default function AgentTasksPage() {
  const params = useParams()
  const agentId = params.agentId as string
  const [viewMode, setViewMode] = useState<ViewMode>('board')
  const searchParams = useSearchParams()
  const router = useRouter()
  const selectedTaskId = searchParams.get('task')

  const setSelectedTaskId = useCallback(
    (id: string | null) => {
      const p = new URLSearchParams(searchParams.toString())
      if (id) {
        p.set('task', id)
      } else {
        p.delete('task')
      }
      router.replace(`/agents/${agentId}/tasks?${p.toString()}`, { scroll: false })
    },
    [searchParams, router, agentId],
  )

  const { data: workspaces = [], isLoading: isWorkspacesLoading } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id ?? ''

  const { data: allTasks = [], isLoading: isTasksLoading } = useTasks(workspaceId)
  const agentsMap = useAgentNameMap(workspaceId)

  // Filter tasks for this agent
  // Tasks may reference agent via agent_profile_id or similar field; filter client-side
  const tasks = allTasks.filter(
    (t) =>
      (t as unknown as Record<string, unknown>).agent_id === agentId ||
      (t as unknown as Record<string, unknown>).agent_profile_id === agentId,
  )

  const isLoading = isWorkspacesLoading || isTasksLoading

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">Tasks</h2>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('board')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  viewMode === 'board'
                    ? 'bg-[var(--surface-5)] text-[var(--text-primary)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                )}
                aria-label="Board view"
              >
                <Kanban className="h-3.5 w-3.5" />
                Board
              </button>
              <button
                type="button"
                onClick={() => setViewMode('list')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  viewMode === 'list'
                    ? 'bg-[var(--surface-5)] text-[var(--text-primary)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                )}
                aria-label="List view"
              >
                <List className="h-3.5 w-3.5" />
                List
              </button>
            </div>

            {workspaceId && (
              <TaskCreateDialog
                workspaceId={workspaceId}
                trigger={
                  <Button size="sm">
                    <Plus className="h-4 w-4" />
                    New Task
                  </Button>
                }
              />
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
          </div>
        ) : viewMode === 'board' ? (
          <TaskBoard
            tasks={tasks}
            workspaceId={workspaceId}
            agentsMap={agentsMap}
            onSelectTask={setSelectedTaskId}
          />
        ) : (
          <TaskListView
            tasks={tasks}
            agentsMap={agentsMap}
            onSelectTask={setSelectedTaskId}
          />
        )}
      </div>

      {selectedTaskId && workspaceId && (
        <TaskDetailPanel
          taskId={selectedTaskId}
          workspaceId={workspaceId}
          onClose={() => setSelectedTaskId(null)}
        />
      )}
    </div>
  )
}

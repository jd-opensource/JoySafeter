'use client'

import { ArrowRight, Kanban, List, Loader2, Plus, Target } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams, useRouter } from 'next/navigation'
import { useCallback, useMemo, useState } from 'react'

import { TaskAttentionPanel } from '@/components/tasks/task-attention-panel'
import { TaskActivitySummary } from '@/components/tasks/task-activity-summary'
import { TaskBoard } from '@/components/tasks/task-board'
import { TaskCreateDialog } from '@/components/tasks/task-create-dialog'
import { TaskDetailPanel } from '@/components/tasks/task-detail-panel'
import { TaskListView } from '@/components/tasks/task-list-view'
import { Button } from '@/components/ui/button'
import { useAgentNameMap, useAgents } from '@/hooks/queries/agents'
import { useTasks } from '@/hooks/queries/tasks'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

type ViewMode = 'board' | 'list'

export default function TasksPage() {
  const { t } = useTranslation()
  const [viewMode, setViewMode] = useState<ViewMode>('board')
  const searchParams = useSearchParams()
  const router = useRouter()
  const selectedTaskId = searchParams.get('task')
  const agentFilter = searchParams.get('agent')

  const setSelectedTaskId = useCallback(
    (id: string | null) => {
      const params = new URLSearchParams(searchParams.toString())
      if (id) {
        params.set('task', id)
      } else {
        params.delete('task')
      }
      router.replace(`/tasks?${params.toString()}`, { scroll: false })
    },
    [searchParams, router],
  )

  const setAgentFilter = useCallback(
    (agentId: string | null) => {
      const params = new URLSearchParams(searchParams.toString())
      if (agentId) {
        params.set('agent', agentId)
      } else {
        params.delete('agent')
      }
      params.delete('task')
      router.replace(`/tasks?${params.toString()}`, { scroll: false })
    },
    [searchParams, router],
  )

  const { projectId, isLoading: isWorkspacesLoading } = useProjectContext()
  const { canEdit } = useUserPermissionsContext()

  const { data: allTasks = [], isLoading: isTasksLoading } = useTasks(projectId)
  const { data: agents = [] } = useAgents(projectId)
  const agentsMap = useAgentNameMap(projectId)

  const isLoading = isWorkspacesLoading || isTasksLoading

  const tasks = useMemo(() => {
    if (!agentFilter) return allTasks
    return allTasks.filter((t) => t.agent_id === agentFilter)
  }, [allTasks, agentFilter])

  const attentionTasks = useMemo(() => allTasks.filter((t) => t.status === 'in_review'), [allTasks])

  const inProgressTasks = useMemo(
    () => allTasks.filter((t) => t.status === 'in_progress'),
    [allTasks],
  )

  const recentlyDoneTasks = useMemo(() => {
    const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000
    return allTasks
      .filter(
        (t) => t.status === 'done' && t.updated_at && new Date(t.updated_at).getTime() > oneDayAgo,
      )
      .sort((a, b) => new Date(b.updated_at!).getTime() - new Date(a.updated_at!).getTime())
  }, [allTasks])

  const filterAgentName = agentFilter ? agentsMap[agentFilter] : null

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      {/* Header */}
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">{t('tasks.title')}</h1>
          </div>

          <div className="flex items-center gap-2">
            {/* Agent filter */}
            <select
              value={agentFilter || ''}
              onChange={(e) => setAgentFilter(e.target.value || null)}
              className="h-8 rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 text-xs text-[var(--text-secondary)]"
            >
              <option value="">{t('tasks.allAgents')}</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>

            {/* View toggle */}
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
                {t('tasks.boardView')}
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
                {t('tasks.listView')}
              </button>
            </div>

            {projectId && canEdit && (
              <TaskCreateDialog
                projectId={projectId}
                trigger={
                  <Button size="sm">
                    <Plus className="mr-1 h-4 w-4" />
                    {t('tasks.newTask')}
                  </Button>
                }
              />
            )}
          </div>
        </div>

        {filterAgentName && (
          <div className="mt-2 flex items-center gap-2 text-xs text-[var(--text-muted)]">
            <span>{t('tasks.filterBy', { name: filterAgentName })}</span>
            <button
              onClick={() => setAgentFilter(null)}
              className="text-[var(--brand-500)] hover:underline"
            >
              {t('tasks.clearFilter')}
            </button>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
          </div>
        ) : allTasks.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            <Target className="h-10 w-10 text-[var(--text-muted)]" />
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">
              {t('tasks.emptyTitle')}
            </h2>
            <p className="text-sm text-[var(--text-muted)]">{t('tasks.emptyDescription')}</p>
            <Link
              href="/agents"
              className="inline-flex items-center gap-1 text-sm font-medium text-[var(--brand-500)] hover:underline"
            >
              {t('tasks.emptyAction')} <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        ) : (
          <>
            {/* Attention + Activity summary — only show when not filtered */}
            {!agentFilter &&
              (attentionTasks.length > 0 ||
                inProgressTasks.length > 0 ||
                recentlyDoneTasks.length > 0) && (
                <div className="space-y-4 px-8 py-6">
                  <TaskAttentionPanel
                    tasks={attentionTasks}
                    agentsMap={agentsMap}
                    onSelectTask={setSelectedTaskId}
                  />
                  <TaskActivitySummary
                    inProgressTasks={inProgressTasks}
                    recentlyDoneTasks={recentlyDoneTasks}
                    agentsMap={agentsMap}
                    onSelectTask={setSelectedTaskId}
                  />
                </div>
              )}

            {/* Full task board/list */}
            <div className="flex-1 overflow-hidden">
              {viewMode === 'board' ? (
                <TaskBoard
                  tasks={tasks}
                  projectId={projectId}
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
          </>
        )}
      </div>

      {selectedTaskId && projectId && (
        <TaskDetailPanel
          taskId={selectedTaskId}
          projectId={projectId}
          onClose={() => setSelectedTaskId(null)}
        />
      )}
    </div>
  )
}

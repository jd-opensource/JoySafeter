'use client'

import { Bot, Clock, Loader2, Play, X, XCircle } from 'lucide-react'
import { useMemo } from 'react'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { ExecutionTimeline } from '@/components/executions/execution-timeline'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAgentProfile, useAgentProfiles } from '@/hooks/queries/agentProfiles'
import {
  useAssignMission,
  useCancelMission,
  useDispatchMission,
  useMission,
} from '@/hooks/queries/missions'
import { cn } from '@/lib/utils'
import type { MissionStatus } from '@/types/missions'
import { MISSION_STATUS_LABELS } from '@/types/missions'

import { PriorityBadge } from './priority-badge'

const STATUS_STYLES: Record<string, string> = {
  backlog: 'bg-gray-100 text-gray-700',
  todo: 'bg-blue-100 text-blue-700',
  in_progress: 'bg-amber-100 text-amber-700',
  in_review: 'bg-purple-100 text-purple-700',
  done: 'bg-green-100 text-green-700',
  blocked: 'bg-red-100 text-red-700',
  cancelled: 'bg-gray-100 text-gray-500',
}

interface MissionDetailPanelProps {
  missionId: string
  workspaceId: string
  onClose: () => void
}

export function MissionDetailPanel({ missionId, workspaceId, onClose }: MissionDetailPanelProps) {
  const { data: mission, isLoading } = useMission(missionId, workspaceId)
  const { data: agent } = useAgentProfile(
    mission?.assignee_id ?? '',
    workspaceId,
    { enabled: mission?.assignee_type === 'agent' && Boolean(mission?.assignee_id) },
  )
  const { data: agents = [] } = useAgentProfiles(workspaceId)

  const assignMission = useAssignMission()
  const dispatchMission = useDispatchMission()
  const cancelMission = useCancelMission()

  const canDispatch = useMemo(() => {
    if (!mission) return false
    const hasAgent = mission.assignee_type === 'agent' && mission.assignee_id
    const notRunning = !mission.current_execution_id
    const validStatus: MissionStatus[] = ['todo', 'in_progress', 'backlog']
    return hasAgent && notRunning && validStatus.includes(mission.status)
  }, [mission])

  const canCancel = Boolean(mission?.current_execution_id)

  const handleAssign = (agentId: string) => {
    assignMission.mutate({ missionId, workspaceId, agentProfileId: agentId })
  }

  const handleDispatch = () => {
    dispatchMission.mutate({ missionId, workspaceId })
  }

  const handleCancel = () => {
    cancelMission.mutate({ missionId, workspaceId })
  }

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-[480px] flex-col border-l border-[var(--border)] bg-[var(--bg)] shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
        <span className="text-xs font-medium text-[var(--text-muted)]">Mission Detail</span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
          aria-label="Close panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {isLoading || !mission ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-5 p-5">
            {/* Title */}
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">{mission.title}</h2>

            {/* Status + Priority */}
            <div className="flex flex-wrap items-center gap-2">
              <PriorityBadge priority={mission.priority} />
              <span
                className={cn(
                  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
                  STATUS_STYLES[mission.status] ?? 'bg-gray-100 text-gray-600',
                )}
              >
                {MISSION_STATUS_LABELS[mission.status]}
              </span>
              {mission.current_execution_id && (
                <span className="inline-flex items-center gap-1 text-xs text-green-600">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
                  </span>
                  Running
                </span>
              )}
            </div>

            {/* Objective */}
            {mission.objective && (
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Objective
                </h3>
                <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
                  {mission.objective}
                </p>
              </section>
            )}

            {/* Description */}
            {mission.description && (
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Description
                </h3>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--text-secondary)]">
                  {mission.description}
                </p>
              </section>
            )}

            {/* Agent */}
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Agent
              </h3>
              {mission.assignee_type === 'agent' && agent ? (
                <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
                  <Bot className="h-5 w-5 text-[var(--text-secondary)]" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-[var(--text-primary)]">{agent.name}</p>
                    <AgentStatusIndicator status={agent.status} />
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-sm text-[var(--text-muted)]">No agent assigned</p>
                  {agents.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {agents.map((a) => (
                        <Button
                          key={a.id}
                          variant="outline"
                          size="sm"
                          onClick={() => handleAssign(a.id)}
                          disabled={assignMission.isPending}
                        >
                          <Bot className="h-3 w-3" />
                          {a.name}
                        </Button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div className="mt-3 flex gap-2">
                {canDispatch && (
                  <Button
                    size="sm"
                    onClick={handleDispatch}
                    disabled={dispatchMission.isPending}
                  >
                    <Play className="h-3.5 w-3.5" />
                    {dispatchMission.isPending ? 'Dispatching...' : 'Dispatch'}
                  </Button>
                )}
                {canCancel && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleCancel}
                    disabled={cancelMission.isPending}
                  >
                    <XCircle className="h-3.5 w-3.5" />
                    {cancelMission.isPending ? 'Cancelling...' : 'Cancel'}
                  </Button>
                )}
              </div>
            </section>

            {/* Execution */}
            {mission.current_execution_id && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Execution
                </h3>
                <div className="overflow-hidden rounded-lg border border-[var(--border)]">
                  <ExecutionTimeline
                    executionId={mission.current_execution_id}
                    workspaceId={workspaceId}
                    compact
                  />
                </div>
              </section>
            )}

            {/* Timestamps */}
            <section className="border-t border-[var(--border)] pt-4">
              <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                <Clock className="h-3 w-3" />
                Created {formatDate(mission.created_at)}
              </div>
              {mission.updated_at !== mission.created_at && (
                <div className="mt-1 flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                  <Clock className="h-3 w-3" />
                  Updated {formatDate(mission.updated_at)}
                </div>
              )}
            </section>
          </div>
        </ScrollArea>
      )}
    </div>
  )
}

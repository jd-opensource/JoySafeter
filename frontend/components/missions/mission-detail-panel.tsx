'use client'

import {
  Bot,
  Calendar,
  Check,
  ChevronDown,
  Clock,
  Loader2,
  Play,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { ExecutionTimeline } from '@/components/executions/execution-timeline'
import { CommentThread } from '@/components/missions/comment-thread'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { InlineRenameInput } from '@/components/ui/inline-rename-input'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useAgentProfile, useAgentProfiles } from '@/hooks/queries/agentProfiles'
import { useExecutions } from '@/hooks/queries/executions'
import {
  useAssignMission,
  useCancelMission,
  useDispatchMission,
  useMission,
  useUpdateMission,
} from '@/hooks/queries/missions'
import { cn } from '@/lib/utils'
import { ACTIVE_EXECUTION_STATUSES } from '@/types/executions'
import type { MissionPriority, MissionStatus } from '@/types/missions'
import {
  MISSION_PRIORITY_LABELS,
  MISSION_STATUS_LABELS,
  MISSION_STATUS_ORDER,
  MISSION_STATUS_STYLES,
} from '@/types/missions'

import { PriorityBadge } from './priority-badge'

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
  const { data: executions = [] } = useExecutions(workspaceId, { mission_id: missionId })

  const assignMission = useAssignMission()
  const dispatchMission = useDispatchMission()
  const cancelMission = useCancelMission()
  const updateMission = useUpdateMission()

  // Editing states
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [isEditingDesc, setIsEditingDesc] = useState(false)
  const [editDesc, setEditDesc] = useState('')
  const [isEditingObj, setIsEditingObj] = useState(false)
  const [editObj, setEditObj] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [agentPickerOpen, setAgentPickerOpen] = useState(false)
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)

  const canDispatch = useMemo(() => {
    if (!mission) return false
    const hasAgent = mission.assignee_type === 'agent' && mission.assignee_id
    const notRunning = !mission.current_execution_id
    const validStatus: MissionStatus[] = ['todo', 'in_progress', 'backlog']
    return hasAgent && notRunning && validStatus.includes(mission.status)
  }, [mission])

  const canCancel = useMemo(() => {
    if (!mission?.current_execution_id) return false
    const currentExec = executions.find((e) => e.id === mission.current_execution_id)
    if (!currentExec) return false
    return ACTIVE_EXECUTION_STATUSES.includes(currentExec.status)
  }, [mission, executions])

  const pastExecutions = useMemo(() => {
    if (!mission) return []
    return executions
      .filter((e) => e.id !== mission.current_execution_id)
      .slice(0, 10)
  }, [executions, mission])

  // Update helpers
  const doUpdate = useCallback(
    (updates: Record<string, unknown>) => {
      updateMission.mutate({ missionId, workspaceId, ...updates })
    },
    [missionId, workspaceId, updateMission],
  )

  const handleTitleSave = () => {
    const trimmed = editTitle.trim()
    if (trimmed && trimmed !== mission?.title) {
      doUpdate({ title: trimmed })
    }
    setIsEditingTitle(false)
  }

  const handleDescSave = () => {
    if (editDesc !== (mission?.description ?? '')) {
      doUpdate({ description: editDesc || null })
    }
    setIsEditingDesc(false)
  }

  const handleObjSave = () => {
    if (editObj !== (mission?.objective ?? '')) {
      doUpdate({ objective: editObj || null })
    }
    setIsEditingObj(false)
  }

  const handleAddTag = () => {
    const tag = tagInput.trim()
    if (!tag || !mission) return
    const current = mission.tags ?? []
    if (!current.includes(tag)) {
      doUpdate({ tags: [...current, tag] })
    }
    setTagInput('')
  }

  const handleRemoveTag = (tag: string) => {
    if (!mission) return
    doUpdate({ tags: (mission.tags ?? []).filter((t) => t !== tag) })
  }

  const handleAssign = (agentId: string) => {
    assignMission.mutate({ missionId, workspaceId, agentProfileId: agentId })
    setAgentPickerOpen(false)
  }

  const handleUnassign = () => {
    doUpdate({ assignee_type: null, assignee_id: null })
    setAgentPickerOpen(false)
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
          className="rounded-md p-1 text-[var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]"
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
            {/* Title — inline edit */}
            {isEditingTitle ? (
              <InlineRenameInput
                value={editTitle}
                onChange={setEditTitle}
                onSave={handleTitleSave}
                onCancel={() => setIsEditingTitle(false)}
              />
            ) : (
              <h2
                className="cursor-pointer rounded px-1 text-lg font-semibold text-[var(--text-primary)] hover:bg-[var(--surface-3)]"
                onClick={() => {
                  setEditTitle(mission.title)
                  setIsEditingTitle(true)
                }}
              >
                {mission.title}
              </h2>
            )}

            {/* Status + Priority selectors */}
            <div className="flex flex-wrap items-center gap-2">
              {/* Priority Select */}
              <Select
                value={mission.priority}
                onValueChange={(v) => doUpdate({ priority: v })}
              >
                <SelectTrigger className="h-auto w-auto border-0 bg-transparent p-0 shadow-none focus:ring-0">
                  <PriorityBadge priority={mission.priority} />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(MISSION_PRIORITY_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* Status Select */}
              <Select
                value={mission.status}
                onValueChange={(v) => doUpdate({ status: v })}
              >
                <SelectTrigger className="h-auto w-auto border-0 bg-transparent p-0 shadow-none focus:ring-0">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium',
                      MISSION_STATUS_STYLES[mission.status] ?? 'bg-[var(--surface-3)] text-[var(--text-muted)]',
                    )}
                  >
                    {MISSION_STATUS_LABELS[mission.status]}
                    <ChevronDown className="h-3 w-3 opacity-50" />
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {MISSION_STATUS_ORDER.map((s) => (
                    <SelectItem key={s} value={s}>
                      {MISSION_STATUS_LABELS[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {canCancel && (
                <span className="inline-flex items-center gap-1 text-xs text-[var(--status-success)]">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--status-success)] opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--status-success)]" />
                  </span>
                  Running
                </span>
              )}
            </div>

            {/* Objective — click to edit */}
            <section>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Objective
              </h3>
              {isEditingObj ? (
                <div className="space-y-1.5">
                  <Textarea
                    value={editObj}
                    onChange={(e) => setEditObj(e.target.value)}
                    rows={2}
                    autoFocus
                    className="text-sm"
                  />
                  <div className="flex gap-1">
                    <Button size="sm" variant="outline" onClick={handleObjSave}>Save</Button>
                    <Button size="sm" variant="ghost" onClick={() => setIsEditingObj(false)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <p
                  className="cursor-pointer rounded px-1 text-sm leading-relaxed text-[var(--text-secondary)] hover:bg-[var(--surface-3)]"
                  onClick={() => {
                    setEditObj(mission.objective ?? '')
                    setIsEditingObj(true)
                  }}
                >
                  {mission.objective || <span className="italic text-[var(--text-muted)]">Click to add objective...</span>}
                </p>
              )}
            </section>

            {/* Description — click to edit */}
            <section>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Description
              </h3>
              {isEditingDesc ? (
                <div className="space-y-1.5">
                  <Textarea
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    rows={4}
                    autoFocus
                    className="text-sm"
                  />
                  <div className="flex gap-1">
                    <Button size="sm" variant="outline" onClick={handleDescSave}>Save</Button>
                    <Button size="sm" variant="ghost" onClick={() => setIsEditingDesc(false)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <p
                  className="cursor-pointer rounded px-1 text-sm leading-relaxed whitespace-pre-wrap text-[var(--text-secondary)] hover:bg-[var(--surface-3)]"
                  onClick={() => {
                    setEditDesc(mission.description ?? '')
                    setIsEditingDesc(true)
                  }}
                >
                  {mission.description || <span className="italic text-[var(--text-muted)]">Click to add description...</span>}
                </p>
              )}
            </section>

            {/* Tags editor */}
            <section>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Tags
              </h3>
              <div className="flex flex-wrap items-center gap-1.5">
                {(mission.tags ?? []).map((tag) => (
                  <Badge key={tag} variant="secondary" className="gap-1 pr-1">
                    {tag}
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(tag)}
                      className="rounded-full p-0.5 hover:bg-[var(--surface-5)]"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </Badge>
                ))}
                <Input
                  placeholder="Add tag..."
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleAddTag()
                    }
                  }}
                  className="h-6 w-24 border-dashed px-2 text-xs"
                />
              </div>
            </section>

            {/* Due Date */}
            <section>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Due Date
              </h3>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                  <input
                    type="date"
                    value={mission.due_date ? new Date(mission.due_date).toISOString().split('T')[0] : ''}
                    onChange={(e) => doUpdate({ due_date: e.target.value || null })}
                    className="h-7 rounded border border-[var(--border)] bg-transparent px-2 text-xs text-[var(--text-secondary)] outline-none focus:ring-1 focus:ring-[var(--brand-400)]"
                  />
                </div>
                {mission.due_date && (
                  <button
                    type="button"
                    onClick={() => doUpdate({ due_date: null })}
                    className="text-xs text-[var(--text-muted)] hover:text-[var(--status-error)]"
                  >
                    Clear
                  </button>
                )}
              </div>
            </section>

            {/* Agent — combobox picker */}
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Agent
              </h3>
              {mission.assignee_type === 'agent' && agent ? (
                <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-3)] p-3">
                  <Bot className="h-5 w-5 text-[var(--text-secondary)]" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-[var(--text-primary)]">{agent.name}</p>
                    <AgentStatusIndicator status={agent.status} />
                  </div>
                  <Popover open={agentPickerOpen} onOpenChange={setAgentPickerOpen}>
                    <PopoverTrigger asChild>
                      <Button variant="ghost" size="sm" className="text-xs">
                        Change
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-60 p-0" align="end">
                      <AgentPickerContent
                        agents={agents}
                        currentAgentId={mission.assignee_id}
                        onSelect={handleAssign}
                        onUnassign={handleUnassign}
                      />
                    </PopoverContent>
                  </Popover>
                </div>
              ) : (
                <Popover open={agentPickerOpen} onOpenChange={setAgentPickerOpen}>
                  <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" className="w-full justify-start text-[var(--text-muted)]">
                      <Bot className="mr-2 h-3.5 w-3.5" />
                      Assign an agent...
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-60 p-0" align="start">
                    <AgentPickerContent
                      agents={agents}
                      onSelect={handleAssign}
                    />
                  </PopoverContent>
                </Popover>
              )}

              {/* Action buttons */}
              <div className="mt-3 flex gap-2">
                {canDispatch && (
                  <Button
                    size="sm"
                    onClick={() => dispatchMission.mutate({ missionId, workspaceId })}
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
                    onClick={() => cancelMission.mutate({ missionId, workspaceId })}
                    disabled={cancelMission.isPending}
                  >
                    <XCircle className="h-3.5 w-3.5" />
                    {cancelMission.isPending ? 'Cancelling...' : 'Cancel Execution'}
                  </Button>
                )}
              </div>
            </section>

            {/* Current Execution */}
            {mission.current_execution_id && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Current Execution
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

            {/* Past Executions */}
            {pastExecutions.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Past Executions
                </h3>
                <div className="space-y-1.5">
                  {pastExecutions.map((exec) => (
                    <PastExecutionRow key={exec.id} execution={exec} workspaceId={workspaceId} />
                  ))}
                </div>
              </section>
            )}

            {/* Comments */}
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Comments
              </h3>
              <CommentThread missionId={missionId} workspaceId={workspaceId} />
            </section>

            {/* Cancel Mission */}
            <section className="border-t border-[var(--border)] pt-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                  <Clock className="h-3 w-3" />
                  Created {formatDate(mission.created_at)}
                </div>
                {mission.status !== 'cancelled' && !mission.current_execution_id && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-[var(--text-muted)] hover:text-[var(--status-error)]"
                    onClick={() => setShowCancelConfirm(true)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Cancel Mission
                  </Button>
                )}
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

      <ConfirmDialog
        open={showCancelConfirm}
        onOpenChange={setShowCancelConfirm}
        title="Cancel Mission"
        description="This will move the mission to Cancelled status. This action can be undone by changing the status back."
        confirmLabel="Cancel Mission"
        variant="destructive"
        onConfirm={() => {
          doUpdate({ status: 'cancelled' })
          setShowCancelConfirm(false)
        }}
      />
    </div>
  )
}

// --- Internal sub-components ---

function AgentPickerContent({
  agents,
  currentAgentId,
  onSelect,
  onUnassign,
}: {
  agents: { id: string; name: string }[]
  currentAgentId?: string | null
  onSelect: (agentId: string) => void
  onUnassign?: () => void
}) {
  return (
    <Command>
      <CommandInput placeholder="Search agents..." />
      <CommandList>
        <CommandEmpty>No agents found.</CommandEmpty>
        <CommandGroup>
          {agents.map((a) => (
            <CommandItem key={a.id} value={a.name} onSelect={() => onSelect(a.id)}>
              <Bot className="mr-2 h-3.5 w-3.5" />
              {a.name}
              {a.id === currentAgentId && (
                <Check className="ml-auto h-3.5 w-3.5 text-[var(--brand-400)]" />
              )}
            </CommandItem>
          ))}
        </CommandGroup>
        {onUnassign && (
          <CommandGroup>
            <CommandItem onSelect={onUnassign} className="text-[var(--status-error)]">
              <X className="mr-2 h-3.5 w-3.5" />
              Unassign
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>
    </Command>
  )
}

function PastExecutionRow({ execution, workspaceId }: { execution: { id: string; status: string; started_at?: string | null; finished_at?: string | null }; workspaceId: string }) {
  const [expanded, setExpanded] = useState(false)

  const statusColor: Record<string, string> = {
    completed: 'bg-[var(--status-success-bg)] text-[var(--status-success)]',
    failed: 'bg-[var(--status-error-bg)] text-[var(--status-error)]',
    cancelled: 'bg-[var(--surface-3)] text-[var(--text-muted)]',
  }

  const duration = useMemo(() => {
    if (!execution.started_at || !execution.finished_at) return null
    const ms = new Date(execution.finished_at).getTime() - new Date(execution.started_at).getTime()
    if (ms < 60_000) return `${Math.round(ms / 1000)}s`
    return `${Math.round(ms / 60_000)}m`
  }, [execution.started_at, execution.finished_at])

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-[var(--surface-3)]"
      >
        <span
          className={cn(
            'inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium',
            statusColor[execution.status] ?? 'bg-[var(--surface-3)] text-[var(--text-muted)]',
          )}
        >
          {execution.status}
        </span>
        {execution.started_at && (
          <span className="text-[var(--text-muted)]">
            {new Date(execution.started_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
        {duration && <span className="text-[var(--text-muted)]">({duration})</span>}
        <ChevronDown className={cn('ml-auto h-3 w-3 text-[var(--text-muted)] transition-transform', expanded && 'rotate-180')} />
      </button>
      {expanded && (
        <div className="mt-1 overflow-hidden rounded-lg border border-[var(--border)]">
          <ExecutionTimeline executionId={execution.id} workspaceId={workspaceId} compact isLive={false} />
        </div>
      )}
    </div>
  )
}

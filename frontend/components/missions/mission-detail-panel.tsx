'use client'

import {
  Archive,
  Bot,
  Check,
  ChevronDown,
  Clock,
  ExternalLink,
  Loader2,
  Play,
  Square,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { useCallback, useMemo, useState } from 'react'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { ExecutionTimeline } from '@/components/executions/execution-timeline'
import { CommentThread } from '@/components/missions/comment-thread'
import { PulsingDot } from '@/components/ui/pulsing-dot'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { InlineRenameInput } from '@/components/ui/inline-rename-input'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useAgentProfile, useAgentProfiles } from '@/hooks/queries/agentProfiles'
import { useExecutions, useCancelExecution } from '@/hooks/queries/executions'
import {
  useAssignMission,
  useCancelMission,
  useDispatchMission,
  useMission,
  useMissionTransitions,
  useUpdateMission,
} from '@/hooks/queries/missions'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError, getErrorMessage } from '@/lib/utils/toast'
import { ACTIVE_EXECUTION_STATUSES } from '@/types/executions'
import type { MissionPriority, MissionStatus, UpdateMissionRequest } from '@/types/missions'
import {
  DEFAULT_MANUAL_TRANSITIONS,
  MISSION_PRIORITY_LABELS,
  MISSION_STATUS_LABELS,
  MISSION_STATUS_ORDER,
  MISSION_STATUS_STYLES,
  TERMINAL_MISSION_STATUSES,
} from '@/types/missions'

import { PriorityBadge } from './priority-badge'

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface MissionDetailPanelProps {
  missionId: string
  workspaceId: string
  onClose: () => void
}

export function MissionDetailPanel({ missionId, workspaceId, onClose }: MissionDetailPanelProps) {
  const { t } = useTranslation()
  const { data: mission, isLoading } = useMission(missionId, workspaceId)
  const { data: agent } = useAgentProfile(
    mission?.assignee_id ?? '',
    workspaceId,
    { enabled: mission?.assignee_type === 'agent' && Boolean(mission?.assignee_id) },
  )
  const { data: agents = [] } = useAgentProfiles(workspaceId, { enabled: Boolean(workspaceId) })
  const { data: executions = [] } = useExecutions(workspaceId, { mission_id: missionId })
  const { data: transitions } = useMissionTransitions(workspaceId)
  const effectiveTransitions = transitions ?? DEFAULT_MANUAL_TRANSITIONS

  const assignMission = useAssignMission()
  const dispatchMission = useDispatchMission()
  const cancelMission = useCancelMission()
  const cancelExecution = useCancelExecution()
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
  const [timelineExpanded, setTimelineExpanded] = useState(false)

  const canDispatch = useMemo(() => {
    if (!mission) return false
    const hasAgent = mission.assignee_type === 'agent' && mission.assignee_id
    const notRunning = !mission.current_execution_id
    const validStatus: MissionStatus[] = ['todo', 'in_progress', 'in_review', 'backlog']
    return hasAgent && notRunning && validStatus.includes(mission.status)
  }, [mission])

  const currentExecution = useMemo(
    () => mission?.current_execution_id ? executions.find((e) => e.id === mission.current_execution_id) : undefined,
    [mission, executions],
  )

  const canCancel = currentExecution ? ACTIVE_EXECUTION_STATUSES.includes(currentExecution.status) : false

  const pastExecutionCount = executions.length - (currentExecution ? 1 : 0)

  const onMutationError = useCallback((err: unknown) => toastError(getErrorMessage(err, t('common.operationFailed'))), [t])

  const doUpdate = useCallback(
    (updates: Partial<UpdateMissionRequest>) => {
      updateMission.mutate(
        { missionId, workspaceId, ...updates },
        { onError: onMutationError },
      )
    },
    [missionId, workspaceId, updateMission, onMutationError],
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
      doUpdate({ description: editDesc || undefined })
    }
    setIsEditingDesc(false)
  }

  const handleObjSave = () => {
    if (editObj !== (mission?.objective ?? '')) {
      doUpdate({ objective: editObj || undefined })
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
    doUpdate({ tags: (mission.tags ?? []).filter((v) => v !== tag) })
  }

  const handleAssign = (agentId: string) => {
    assignMission.mutate(
      { missionId, workspaceId, agentProfileId: agentId },
      { onError: onMutationError },
    )
    setAgentPickerOpen(false)
  }

  const handleUnassign = () => {
    doUpdate({ assignee_type: null, assignee_id: null })
    setAgentPickerOpen(false)
  }

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-[480px] flex-col border-l border-[var(--border)] bg-[var(--bg)] shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
        <span className="text-xs font-medium text-[var(--text-muted)]">{t('missions.detailTitle')}</span>
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
                onValueChange={(v) => doUpdate({ priority: v as MissionPriority })}
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
                onValueChange={(v) => {
                  if (mission.current_execution_id && (TERMINAL_MISSION_STATUSES as readonly string[]).includes(v)) return
                  doUpdate({ status: v as MissionStatus })
                }}
              >
                <SelectTrigger className="h-auto w-auto border-0 bg-transparent p-0 shadow-none [&>span]:line-clamp-none focus:ring-0">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium',
                      MISSION_STATUS_STYLES[mission.status] ?? 'bg-[var(--surface-3)] text-[var(--text-muted)]',
                    )}
                  >
                    {MISSION_STATUS_LABELS[mission.status]}
                  </span>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem key={mission.status} value={mission.status}>
                    {MISSION_STATUS_LABELS[mission.status]}
                  </SelectItem>
                  {(effectiveTransitions[mission.status] ?? []).map((s) => (
                    <SelectItem
                      key={s}
                      value={s}
                      disabled={Boolean(mission.current_execution_id) && (TERMINAL_MISSION_STATUSES as readonly string[]).includes(s)}
                    >
                      {MISSION_STATUS_LABELS[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {canCancel && (
                <span className="inline-flex items-center gap-1 text-xs text-[var(--status-success)]">
                  <PulsingDot />
                  {t('missions.running')}
                </span>
              )}
            </div>

            {/* Objective + Description */}
            <section className="space-y-3">
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  {t('missions.objective')}
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
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  {t('missions.description')}
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
              </div>
            </section>

            {/* Metadata card */}
            <section className="overflow-hidden rounded-lg border border-[var(--border)]">
              {/* Tags */}
              <div className="flex items-start gap-3 px-3 py-2.5">
                <span className="shrink-0 pt-0.5 text-xs font-medium text-[var(--text-muted)]">{t('missions.tags')}</span>
                <div className="flex flex-1 flex-wrap items-center gap-1.5">
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
              </div>

              <div className="h-px bg-[var(--border)]" />

              {/* Due Date */}
              <div className="flex items-center justify-between px-3 py-2.5">
                <span className="text-xs font-medium text-[var(--text-muted)]">{t('missions.dueDate')}</span>
                <div className="flex items-center gap-2">
                  <input
                    type="date"
                    value={mission.due_date ? new Date(mission.due_date).toISOString().split('T')[0] : ''}
                    onChange={(e) => doUpdate({ due_date: e.target.value || null })}
                    className="h-7 rounded border border-[var(--border)] bg-transparent px-2 text-xs text-[var(--text-secondary)] outline-none focus:ring-1 focus:ring-[var(--brand-400)]"
                  />
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
              </div>

              <div className="h-px bg-[var(--border)]" />

              {/* Agent */}
              <div className="flex items-center justify-between px-3 py-2.5">
                <span className="text-xs font-medium text-[var(--text-muted)]">{t('missions.agent')}</span>
                {mission.assignee_type === 'agent' && agent ? (
                  <div className="flex items-center gap-2">
                    <Bot className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                    <span className="text-sm font-medium text-[var(--text-primary)]">{agent.name}</span>
                    <AgentStatusIndicator status={agent.status} />
                    <Popover open={agentPickerOpen} onOpenChange={setAgentPickerOpen}>
                      <PopoverTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-6 px-2 text-xs">
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
                      <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-xs text-[var(--text-muted)]">
                        <Bot className="h-3 w-3" />
                        Assign...
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-60 p-0" align="end">
                      <AgentPickerContent agents={agents} onSelect={handleAssign} />
                    </PopoverContent>
                  </Popover>
                )}
              </div>

              <div className="h-px bg-[var(--border)]" />

              {/* Auto Approve */}
              <div className="flex items-center justify-between px-3 py-2.5">
                <div className="space-y-0.5">
                  <p className="text-xs font-medium text-[var(--text-primary)]">Auto Approve</p>
                  <p className="text-[10px] text-[var(--text-muted)]">
                    {mission.auto_approve
                      ? 'Tool calls auto-approved, completes to Done'
                      : 'Tool calls need approval, completes to In Review'}
                  </p>
                </div>
                <Switch
                  checked={mission.auto_approve}
                  onCheckedChange={(checked) => doUpdate({ auto_approve: checked })}
                />
              </div>
            </section>

            {/* Dispatch */}
            {canDispatch && (
              <Button
                size="sm"
                onClick={() => {
                  dispatchMission.mutate({ missionId, workspaceId }, {
                    onSuccess: () => toastSuccess(t('runs.dispatchedToast')),
                    onError: onMutationError,
                  })
                }}
                disabled={dispatchMission.isPending}
              >
                <Play className="h-3.5 w-3.5" />
                {dispatchMission.isPending ? t('runs.dispatching') : t('runs.dispatch')}
              </Button>
            )}

            {mission.current_execution_id && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  {t('missions.currentExecution')}
                </h3>
                <div className="overflow-hidden rounded-lg border border-[var(--border)]">
                  <div className="flex items-center justify-between px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <PulsingDot className="text-[var(--status-success)]" />
                      <Badge variant="outline" className="text-xs">
                        {currentExecution?.status ?? 'running'}
                      </Badge>
                      {canCancel && (
                        <Button
                          variant="destructive"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          onClick={() => cancelExecution.mutate(
                            { executionId: mission.current_execution_id!, workspaceId },
                            { onError: onMutationError },
                          )}
                          disabled={cancelExecution.isPending}
                        >
                          <Square className="mr-1 h-3 w-3" />
                          {cancelExecution.isPending ? t('missions.stoppingRun') : t('missions.stopRun')}
                        </Button>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 gap-1 px-2 text-xs"
                      onClick={() => setTimelineExpanded(!timelineExpanded)}
                    >
                      <ChevronDown className={cn('h-3 w-3 transition-transform', timelineExpanded && 'rotate-180')} />
                      {timelineExpanded ? t('missions.collapseTimeline') : t('missions.expandTimeline')}
                    </Button>
                  </div>
                  {timelineExpanded && (
                    <div className="border-t border-[var(--border)]">
                      <ExecutionTimeline
                        executionId={mission.current_execution_id}
                        workspaceId={workspaceId}
                        compact
                        missionId={missionId}
                      />
                    </div>
                  )}
                </div>
                <Link
                  href={`/runs?tab=executions&mission=${missionId}`}
                  className="mt-1.5 flex items-center gap-1 text-xs text-[var(--brand-400)] hover:underline"
                >
                  <ExternalLink className="h-3 w-3" />
                  {t('missions.viewFullLogs')}
                </Link>
              </section>
            )}

            {pastExecutionCount > 0 && (
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  {t('runs.pastExecutions')}
                </h3>
                <p className="text-xs text-[var(--text-muted)]">
                  {t('runs.pastExecutionsCount', { count: pastExecutionCount })} —{' '}
                  <Link
                    href={`/runs?tab=executions&mission=${missionId}`}
                    className="text-[var(--brand-400)] hover:underline"
                  >
                    {t('runs.pastExecutionsLink')}
                  </Link>
                </p>
              </section>
            )}

            {/* Comments */}
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {t('missions.comments')}
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
                {!TERMINAL_MISSION_STATUSES.includes(mission.status) && !mission.current_execution_id && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                    onClick={() => setShowCancelConfirm(true)}
                  >
                    <Archive className="h-3.5 w-3.5" />
                    {t('missions.archive')}
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
        title={t('missions.archiveConfirmTitle')}
        description={t('missions.archiveConfirmDesc')}
        confirmLabel={t('missions.archiveConfirm')}
        variant="default"
        onConfirm={() => {
          cancelMission.mutate(
            { missionId, workspaceId },
            { onError: onMutationError },
          )
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


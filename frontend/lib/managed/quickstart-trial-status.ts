import type { QuickstartTaskSummary, SessionEvent } from '@/types/managed'

export const QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS = 30_000

export type QuickstartTrialStatus =
  | 'idle'
  | 'testing'
  | 'success'
  | 'error'
  | 'runtime_unavailable'

type QuickstartTrialTask = Pick<
  QuickstartTaskSummary,
  'status' | 'created_at' | 'started_at' | 'completed_at' | 'error'
>

const TERMINAL_ERROR_TASK_STATUSES = new Set(['failed', 'aborted', 'timeout', 'cancelled'])
const WAITING_TASK_STATUSES = new Set(['pending', 'scheduling'])

export function deriveQuickstartTrialStatus({
  isSessionActive,
  events,
  task,
  nowMs,
}: {
  isSessionActive: boolean
  events: Pick<SessionEvent, 'type'>[]
  task: QuickstartTrialTask | null
  nowMs: number
}): QuickstartTrialStatus {
  if (!isSessionActive || !events.some((event) => event.type === 'user.message')) return 'idle'

  if (events.some((event) => event.type === 'session.status_terminated')) return 'error'

  const hasAgentMessage = events.some((event) => event.type === 'agent.message')
  const isIdle = events.some((event) => event.type === 'session.status_idle')
  if (hasAgentMessage && isIdle) return 'success'

  if (task && TERMINAL_ERROR_TASK_STATUSES.has(task.status)) return 'error'

  if (task && WAITING_TASK_STATUSES.has(task.status)) {
    const createdAtMs = Date.parse(task.created_at)
    if (
      Number.isFinite(createdAtMs) &&
      nowMs - createdAtMs >= QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS
    ) {
      return 'runtime_unavailable'
    }
  }

  return 'testing'
}

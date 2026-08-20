import type { QuickstartTaskSummary, SessionEvent } from '@/types/managed'

export const QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS = 30_000

export type QuickstartTrialStatus =
  | 'idle'
  | 'testing'
  | 'response_received'
  | 'access_rejected'
  | 'error'
  | 'runtime_unavailable'

type QuickstartTrialTask = Pick<
  QuickstartTaskSummary,
  'status' | 'created_at' | 'started_at' | 'completed_at' | 'error'
>

const TERMINAL_ERROR_TASK_STATUSES = new Set(['failed', 'aborted', 'timeout', 'cancelled'])
const WAITING_TASK_STATUSES = new Set(['pending', 'scheduling'])
const ACCESS_REJECTION_PATTERN =
  /access denied|permission denied|not authorized|unauthorized|forbidden|policy (?:denied|rejected)|credential (?:denied|rejected)/i

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

  if (
    task &&
    TERMINAL_ERROR_TASK_STATUSES.has(task.status) &&
    task.error &&
    ACCESS_REJECTION_PATTERN.test(task.error)
  ) {
    return 'access_rejected'
  }

  if (events.some((event) => event.type === 'session.status_terminated')) return 'error'

  const hasAgentMessage = events.some((event) => event.type === 'agent.message')
  // The turn is "settled" once the runtime signals completion. Engines are not
  // consistent about emitting session.status_idle, so also accept a task.complete
  // event or a completed task status — otherwise a finished trial can hang on
  // "testing" forever even though the agent already replied.
  const turnSettled =
    events.some(
      (event) => event.type === 'session.status_idle' || event.type === 'task.complete',
    ) || task?.status === 'completed'
  if (hasAgentMessage && turnSettled) return 'response_received'

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

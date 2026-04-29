import type { ExecutionEvent, ExecutionEventType } from '@/types/agent-run'
import type { AppErrorPayload } from '@/types/agent-run'

export interface ExecutionConnectionState {
  isConnected: boolean
  authExpired?: boolean
}

export interface ExecutionSnapshotFrame {
  type: 'snapshot'
  execution_id: string
  last_seq: number
  status: string
  events: ExecutionEvent[]
  error?: AppErrorPayload | null
}

export interface ExecutionEventFrame {
  type: 'event'
  execution_id: string
  seq: number
  event_type: ExecutionEventType
  payload: Record<string, unknown>
  created_at: string
}

export interface ExecutionCompletedFrame {
  type: 'execution_completed'
  execution_id: string
  run_id: string
  status: string
  error?: AppErrorPayload
}

export interface ExecutionReplayDoneFrame {
  type: 'replay_done'
  execution_id: string
  last_seq: number
}

export interface ExecutionWsErrorFrame {
  type: 'ws_error'
  error: AppErrorPayload
}

export interface ExecutionObservationFrame {
  type: 'observation'
  execution_id: string
  event: 'span_open' | 'span_close' | 'span_update' | 'trace_complete'
  observation: Record<string, unknown> | null
  data: Record<string, unknown>
  timestamp: string
}

export type IncomingExecutionWsFrame =
  | ExecutionSnapshotFrame
  | ExecutionEventFrame
  | ExecutionCompletedFrame
  | ExecutionReplayDoneFrame
  | ExecutionWsErrorFrame
  | ExecutionObservationFrame

export interface ExecutionSubscriptionCallbacks {
  onSnapshot?: (frame: ExecutionSnapshotFrame) => void
  onEvent?: (frame: ExecutionEventFrame) => void
  onCompleted?: (frame: ExecutionCompletedFrame) => void
  onReplayDone?: (frame: ExecutionReplayDoneFrame) => void
  onObservation?: (frame: ExecutionObservationFrame) => void
  onError?: (error: AppErrorPayload) => void
}

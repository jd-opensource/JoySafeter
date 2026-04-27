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

export type IncomingExecutionWsFrame =
  | ExecutionSnapshotFrame
  | ExecutionEventFrame
  | ExecutionCompletedFrame
  | ExecutionReplayDoneFrame
  | ExecutionWsErrorFrame

export interface ExecutionSubscriptionCallbacks {
  onSnapshot?: (frame: ExecutionSnapshotFrame) => void
  onEvent?: (frame: ExecutionEventFrame) => void
  onCompleted?: (frame: ExecutionCompletedFrame) => void
  onReplayDone?: (frame: ExecutionReplayDoneFrame) => void
  onError?: (error: AppErrorPayload) => void
}

import type { ExecutionEvent, ExecutionEventType } from '@/types/agent-run'

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
}

export interface ExecutionEventFrame {
  type: 'event'
  execution_id: string
  seq: number
  event_type: ExecutionEventType
  payload: Record<string, unknown>
  created_at: string
}

export interface ExecutionStatusFrame {
  type: 'execution_status'
  execution_id: string
  status: string
}

export interface ExecutionCompletedFrame {
  type: 'execution_completed'
  execution_id: string
  run_id: string
  status: string
}

export interface ExecutionReplayDoneFrame {
  type: 'replay_done'
  execution_id: string
  last_seq: number
}

export interface ExecutionWsErrorFrame {
  type: 'ws_error'
  message: string
}

export type IncomingExecutionWsFrame =
  | ExecutionSnapshotFrame
  | ExecutionEventFrame
  | ExecutionStatusFrame
  | ExecutionCompletedFrame
  | ExecutionReplayDoneFrame
  | ExecutionWsErrorFrame

export interface ExecutionSubscriptionCallbacks {
  onSnapshot?: (frame: ExecutionSnapshotFrame) => void
  onEvent?: (frame: ExecutionEventFrame) => void
  onStatus?: (frame: ExecutionStatusFrame) => void
  onError?: (message: string) => void
}

export interface RunConnectionState {
  isConnected: boolean
  authExpired?: boolean
}

export interface RunSnapshotFrame {
  type: 'snapshot'
  run_id: string
  last_seq: number
  data: Record<string, any>
}

export interface RunEventFrame {
  type: 'event'
  run_id: string
  seq: number
  event_type: string
  data: Record<string, any>
  trace_id?: string | null
  observation_id?: string | null
  parent_observation_id?: string | null
  created_at?: string
}

export interface RunReplayDoneFrame {
  type: 'replay_done'
  run_id: string
  last_seq: number
}

export interface RunStatusFrame {
  type: 'run_status'
  run_id: string
  status: string
  error_code?: string | null
  error_message?: string | null
}

export interface RunWsErrorFrame {
  type: 'ws_error'
  message: string
}

export interface RunPongFrame {
  type: 'pong'
}

export type IncomingRunWsFrame =
  | RunSnapshotFrame
  | RunEventFrame
  | RunReplayDoneFrame
  | RunStatusFrame
  | RunWsErrorFrame
  | RunPongFrame

export interface RunSubscriptionCallbacks {
  onSnapshot?: (frame: RunSnapshotFrame) => void
  onEvent?: (frame: RunEventFrame) => void
  onReplayDone?: (frame: RunReplayDoneFrame) => void
  onStatus?: (frame: RunStatusFrame) => void
  onError?: (message: string) => void
}

export interface RunWsClient {
  connect(): Promise<void>
  disconnect(): void
  subscribeConnectionState(listener: (state: RunConnectionState) => void): () => void
  getConnectionState(): RunConnectionState
  subscribe(runId: string, afterSeq: number, callbacks?: RunSubscriptionCallbacks): Promise<void>
  unsubscribe(runId: string): void
}

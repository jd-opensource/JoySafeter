import type { ChatStreamEvent } from '@/services/chatBackend'

export interface IncomingChatAcceptedEvent {
  type: 'accepted'
  request_id: string
  thread_id?: string
  run_id?: string
  timestamp?: number
  data?: {
    status?: string
  }
}

export type IncomingChatWsEvent = Partial<ChatStreamEvent> & {
  type?: string
  request_id?: string
  message?: string
  thread_id?: string
  data?: any
  run_id?: string
  node_name?: string
  timestamp?: number
}

export interface ChatResumeCommand {
  update?: Record<string, unknown>
  goto?: string | null
}

export interface ChatSendFile {
  filename: string
  path: string
  size: number
}

export interface ChatSendInput {
  message: string
  files?: ChatSendFile[]
  model?: string
}

export interface SkillCreatorExtension {
  kind: 'skill_creator'
  runId?: string | null
  editSkillId?: string | null
}

export interface ChatExtension {
  kind: 'chat'
  runId?: string | null
}

export interface ChatSendParams {
  requestId?: string
  threadId?: string | null
  graphId?: string | null
  input: ChatSendInput
  extension?: SkillCreatorExtension | ChatExtension | null
  metadata?: Record<string, unknown>
  onEvent?: (evt: ChatStreamEvent) => void
  onAccepted?: (evt: IncomingChatAcceptedEvent) => void
}

export interface ChatResumeParams {
  requestId?: string
  threadId: string
  command: ChatResumeCommand
  onEvent?: (evt: ChatStreamEvent) => void
  onAccepted?: (evt: IncomingChatAcceptedEvent) => void
}

export type ChatTerminal = 'done' | 'interrupt' | 'stopped'

export interface ChatTerminalResult {
  requestId: string
  threadId?: string
  terminal: ChatTerminal
}

export interface ConnectionState {
  isConnected: boolean
  authExpired?: boolean
}

export interface ChatWsClient {
  connect(): Promise<void>
  getConnectionState(): ConnectionState
  subscribeConnectionState(listener: (state: ConnectionState) => void): () => void
  sendChat(params: ChatSendParams): Promise<ChatTerminalResult>
  sendResume(params: ChatResumeParams): Promise<ChatTerminalResult>
  stopByThreadId(threadId: string): void
  stopByRequestId(requestId: string): void
  dispose(): void
}

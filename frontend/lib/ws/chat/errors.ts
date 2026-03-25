export type ChatWsErrorCode =
  | 'WS_PROTOCOL_ERROR'
  | 'WS_NOT_CONNECTED'
  | 'WS_CONNECTION_FAILED'
  | 'WS_CONNECTION_LOST'
  | 'CHAT_EXECUTION_ERROR'

export class ChatWsError extends Error {
  code: ChatWsErrorCode
  details?: Record<string, unknown>

  constructor(code: ChatWsErrorCode, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ChatWsError'
    this.code = code
    this.details = details
  }
}

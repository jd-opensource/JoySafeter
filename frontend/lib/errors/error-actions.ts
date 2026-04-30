import type { AppErrorPayload, UserAction } from '@/types/agent-run'

export function getErrorAction(error: AppErrorPayload): UserAction | null {
  if (error.user_action) return error.user_action

  if (error.code.startsWith('MODEL_') || error.code === 'BUILD_COPILOT_MODEL_REQUIRED')
    return 'configure_model'
  if (
    error.code.startsWith('AUTH_') ||
    error.code === 'UNAUTHORIZED' ||
    error.code === 'TOKEN_INVALID' ||
    error.code === 'CREDENTIALS_INVALID'
  )
    return 'relogin'

  return error.retryable ? 'retry' : null
}

export function isRetryable(error: AppErrorPayload): boolean {
  return error.retryable ?? false
}

export function isModelConfigError(error: AppErrorPayload): boolean {
  return getErrorAction(error) === 'configure_model'
}

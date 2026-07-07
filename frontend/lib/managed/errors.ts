import { toastError } from '@/lib/utils/toast'

type Translator = (key: string, options?: Record<string, unknown>) => string

export type ManagedErrorEnvelope = {
  code: string
  message: string
  data: Record<string, unknown> | null
  source?: string
  retryable?: boolean
  userAction?: string
  detail?: string
  traceId?: string
  status?: number
}

export function parseApiError(error: unknown): ManagedErrorEnvelope {
  const apiError = error as {
    status?: unknown
    code?: unknown
    message?: unknown
    data?: unknown
    source?: unknown
    retryable?: unknown
    userAction?: unknown
    detail?: unknown
    traceId?: unknown
  }
  const data =
    apiError?.data && typeof apiError.data === 'object'
      ? (apiError.data as Record<string, unknown>)
      : null
  return {
    code: typeof apiError?.code === 'string' ? apiError.code : '',
    message: typeof apiError?.message === 'string' ? apiError.message : '',
    data,
    source: typeof apiError?.source === 'string' ? apiError.source : undefined,
    retryable: typeof apiError?.retryable === 'boolean' ? apiError.retryable : undefined,
    userAction: typeof apiError?.userAction === 'string' ? apiError.userAction : undefined,
    detail: typeof apiError?.detail === 'string' ? apiError.detail : undefined,
    traceId: typeof apiError?.traceId === 'string' ? apiError.traceId : undefined,
    status: typeof apiError?.status === 'number' ? apiError.status : undefined,
  }
}

export function shouldRetryManagedResourceError(failureCount: number, error: unknown): boolean {
  const { code } = parseApiError(error)
  if (
    code === 'FORBIDDEN' ||
    code === 'UNAUTHORIZED' ||
    code === 'NOT_FOUND' ||
    code.endsWith('_NOT_FOUND')
  ) {
    return false
  }
  return failureCount < 2
}

export function getOperationErrorMessage(
  t: Translator,
  error: unknown,
  fallbackKey: string,
): string {
  const { code, message, data } = parseApiError(error)

  if (code === 'SKILL_SECURITY_SCAN_REJECTED') {
    return t('managed.errors.skillSecurityRejected', {
      score: data?.score ?? '-',
      severity: data?.severity ?? '-',
      recommendation: data?.recommendation ?? '-',
      issues: data?.issues_count ?? 0,
    })
  }
  if (code === 'SKILL_SECURITY_SCAN_FAILED') {
    return t('managed.errors.skillSecurityScanFailed', {
      error: data?.error_message ?? '',
    })
  }

  if (code === 'JOYSAFETER_WRITE_REQUIRED' || code === 'WRITE_ACCESS_DENIED') {
    return t('managed.errors.writeRequired')
  }
  if (code === 'JOYSAFETER_ADMIN_REQUIRED') {
    return t('managed.errors.adminRequired')
  }
  if (code === 'NOT_ORG_MEMBER') {
    return t('managed.errors.notOrgMember')
  }
  if (code === 'JOYSAFETER_UNAUTHORIZED' || code === 'UNAUTHORIZED') {
    return t('managed.errors.unauthorized')
  }
  if (code === 'MEMBERSHIP_EXPIRED') {
    return t('managed.errors.membershipExpired')
  }
  if (code === 'PROJECT_ACCESS_DENIED') {
    return t('managed.errors.projectNotFound')
  }
  if (code === 'PROJECT_ARCHIVED') {
    return t('managed.errors.projectArchived')
  }
  if (code === 'RESOURCE_ARCHIVED') {
    return t('managed.errors.resourceArchived')
  }
  if (code === 'NOT_FOUND' || code.endsWith('_NOT_FOUND')) {
    return t('managed.errors.resourceNotFound')
  }
  if (message.trim()) {
    return message
  }
  return t(fallbackKey)
}

export function getOperationErrorMessageWithDetails(
  t: Translator,
  error: unknown,
  fallbackKey: string,
): string {
  const message = getOperationErrorMessage(t, error, fallbackKey)
  const errorEnvelope = parseApiError(error)
  const status = typeof errorEnvelope.status === 'number' ? `HTTP ${errorEnvelope.status}` : ''
  const details = [
    errorEnvelope.code.trim(),
    status,
    errorEnvelope.source?.trim() ?? '',
    errorEnvelope.traceId?.trim() ? `trace ${errorEnvelope.traceId.trim()}` : '',
  ].filter(Boolean)

  return details.length > 0 ? `${message} (${details.join(', ')})` : message
}

export function toastOperationError(
  t: Translator,
  error: unknown,
  fallbackKey = 'common.operationFailed',
  titleKey = 'common.operationFailed',
): void {
  toastError(getOperationErrorMessage(t, error, fallbackKey), t(titleKey))
}

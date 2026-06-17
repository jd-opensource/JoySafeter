import { toastError } from '@/lib/utils/toast'

type Translator = (key: string, options?: Record<string, unknown>) => string

export function shouldRetryManagedResourceError(failureCount: number, error: unknown): boolean {
  const apiError = error as { status?: number; response?: { status?: number } }
  const status = apiError?.status ?? apiError?.response?.status
  if (status === 403 || status === 404) return false
  return failureCount < 2
}

export function getOperationErrorMessage(t: Translator, error: unknown, fallbackKey: string): string {
  const apiError = error as {
    status?: number
    code?: string
    message?: string
    payload?: { message?: string; data?: Record<string, unknown> | null }
    data?: Record<string, unknown> | null
  }
  const code = apiError?.code || ''
  const message = (apiError?.message || apiError?.payload?.message || '').toLowerCase()
  const data = apiError?.data || apiError?.payload?.data || null

  if (message.includes('archived')) {
    return t('managed.errors.resourceArchived')
  }

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
      error: data?.error_message || '',
    })
  }

  if (apiError?.status === 403 || code === 'JOYSAFETER_WRITE_REQUIRED' || code === 'WRITE_ACCESS_DENIED' || message.includes('write access required')) {
    return t('managed.errors.writeRequired')
  }
  if (code === 'JOYSAFETER_ADMIN_REQUIRED') {
    return t('managed.errors.adminRequired')
  }
  if (code === 'NOT_ORG_MEMBER') {
    return t('managed.errors.notOrgMember')
  }
  if (code === 'JOYSAFETER_UNAUTHORIZED' || apiError?.status === 401) {
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
  if (apiError?.status === 404 || code.includes('NOT_FOUND')) {
    return t('managed.errors.resourceNotFound')
  }
  return t(fallbackKey)
}

export function toastOperationError(t: Translator, error: unknown, fallbackKey = 'common.operationFailed', titleKey = 'common.operationFailed'): void {
  toastError(getOperationErrorMessage(t, error, fallbackKey), t(titleKey))
}

import { ApiError } from '@/lib/api-client'

/**
 * Check if an error is a permission/authorization error
 */
export function isPermissionError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return (
      error.status === 403 ||
      error.code === 'FORBIDDEN' ||
      error.code === 'EMAIL_NOT_VERIFIED' ||
      error.code.endsWith('_FORBIDDEN')
    )
  }

  return false
}

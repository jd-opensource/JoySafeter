/**
 * CSRF Token Management
 *
 * Centralized management of CSRF token storage and retrieval to avoid circular dependencies
 */

// CSRF Token in-memory storage
let csrfTokenMemory: string | null = null

function readCsrfTokenFromCookie(): string | null {
  if (typeof document === 'undefined') return null

  const cookieNames = [
    '__Host-csrf_token',
    'csrf_token',
    '__Host-auth_token_csrf',
    'auth_token_csrf',
  ]

  for (const name of cookieNames) {
    const value = document.cookie
      .split('; ')
      .find((row) => row.startsWith(`${name}=`))
      ?.split('=')[1]

    if (value) {
      return decodeURIComponent(value)
    }
  }

  return null
}

/**
 * Set CSRF token (called after successful login)
 */
export function setCsrfToken(token: string): void {
  csrfTokenMemory = token
}

/**
 * Get CSRF token
 * Priority: use the readable cookie first so cross-tab refreshes update stale memory.
 */
export function getCsrfToken(): string | null {
  const cookieToken = readCsrfTokenFromCookie()
  if (cookieToken) {
    csrfTokenMemory = cookieToken
    return cookieToken
  }

  return csrfTokenMemory
}

/**
 * Clear CSRF token (called on logout)
 */
export function clearCsrfToken(): void {
  csrfTokenMemory = null
}

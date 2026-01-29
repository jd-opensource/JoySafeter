/**
 * CSRF Token Management
 *
 * Centralized management of CSRF token storage and retrieval to avoid circular dependencies
 */

// CSRF Token in-memory storage
let csrfTokenMemory: string | null = null

/**
 * Set CSRF token (called after successful login)
 */
export function setCsrfToken(token: string): void {
  csrfTokenMemory = token
}

/**
 * Get CSRF token
 * Priority: get from memory first, fallback to reading from Cookie
 */
export function getCsrfToken(): string | null {
  // Priority: get from memory first
  if (csrfTokenMemory) {
    return csrfTokenMemory
  }

  // Read from Cookie (fallback)
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
      .find(row => row.startsWith(`${name}=`))
      ?.split('=')[1]

    if (value) {
      return decodeURIComponent(value)
    }
  }

  return null
}

/**
 * Clear CSRF token (called on logout)
 */
export function clearCsrfToken(): void {
  csrfTokenMemory = null
}

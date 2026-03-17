/**
 * Application route constants
 */

/**
 * Public route list (pages that don't require login)
 */
export const PUBLIC_ROUTES = [
  '/signin',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/verify',
] as const

/**
 * Check if it's a public route
 */
export function isPublicRoute(pathname: string | null): boolean {
  if (!pathname) return false
  return PUBLIC_ROUTES.some((route) => pathname.startsWith(route))
}

/**
 * Default redirect route after login
 */
export const DEFAULT_AUTHENTICATED_ROUTE = '/'

/**
 * Default sign-in route
 */
export const DEFAULT_SIGNIN_ROUTE = '/signin'

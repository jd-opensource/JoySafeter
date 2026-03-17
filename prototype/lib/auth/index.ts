// Export mock auth system for prototype
export { client as auth, useSession, signIn, signUp, signOut, clearTokens } from './auth-client'

// CSRF stubs
export { clearCsrfToken } from './auth-client'
export function setCsrfToken(_token: string): void {}
export function getCsrfToken(): string | null { return null }

// getSession stub
export const getSession = async () => null

// Type exports
export type { AuthUser, AuthSession, AuthError } from './auth-client'

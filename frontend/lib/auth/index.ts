// Export JWT authentication system
export { client as auth, useSession, signIn, signUp, signOut, authApi, clearTokens } from './auth-client'

// CSRF Token management
export { setCsrfToken, getCsrfToken, clearCsrfToken } from './csrf'

// Compatible with Better Auth's getSession interface
export const getSession = async () => {
  const { authApi: api } = await import('./auth-client')
  return await api.getSession()
}

// Type exports
export type { AuthUser, AuthSession, AuthError } from './auth-client'

// Export JWT authentication system
export { client as auth, useSession, signIn, signUp, signOut, authApi } from './auth-client'

// CSRF Token management
export { setCsrfToken, getCsrfToken, clearCsrfToken } from './csrf'

// Type exports
export type { AuthUser, AuthSession } from './auth-client'
export { ApiError } from './auth-client'

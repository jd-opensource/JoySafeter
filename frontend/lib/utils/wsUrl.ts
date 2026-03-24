import { env as runtimeEnv } from 'next-runtime-env'

/**
 * Returns the WebSocket base URL derived from NEXT_PUBLIC_API_URL (preferred)
 * or the current window origin as a fallback for co-hosted deployments.
 */
export function getWsBaseUrl(): string {
  const apiUrl = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  if (apiUrl) {
    return apiUrl
      .replace(/^https:/, 'wss:')
      .replace(/^http:/, 'ws:')
      .replace(/\/api\/?$/, '')
  }
  if (typeof window !== 'undefined') {
    return window.location.origin.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
  }
  return 'ws://localhost:8000'
}

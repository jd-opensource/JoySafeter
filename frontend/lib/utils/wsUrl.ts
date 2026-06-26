import { env as runtimeEnv } from 'next-runtime-env'

import { createApiError, managedGet } from '@/lib/api-client'

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

/** Fetch a short-lived WS token from the backend and return a ready-to-use WS URL for the given path. */
async function getWsTokenUrl(path: string): Promise<string> {
  const response = await managedGet<{ token?: string }>('auth/ws-token')
  const token = response?.token
  if (!token) {
    throw createApiError(500, 'Invalid WebSocket Token Response', {
      code: 'WEBSOCKET_TOKEN_MISSING',
      message: 'No WebSocket token in response',
      data: { path },
    })
  }
  return `${getWsBaseUrl()}${path}?token=${encodeURIComponent(token)}`
}

/** Fetch a short-lived WS token from the backend and return a ready-to-use notification WS URL. */
export async function getWsNotificationUrl(): Promise<string> {
  return getWsTokenUrl('/ws/notifications')
}

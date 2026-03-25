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

/** Fetch a short-lived WS token from the backend and return a ready-to-use WS URL for the given path. */
async function getWsTokenUrl(path: string): Promise<string> {
  const apiUrl = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'
  const base = apiUrl.replace(/\/api\/?$/, '')
  const res = await fetch(`${base}/api/v1/auth/ws-token`, { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to obtain WS token')
  const json = await res.json()
  const token: string = json?.data?.token
  if (!token) throw new Error('No WS token in response')
  return `${getWsBaseUrl()}${path}?token=${encodeURIComponent(token)}`
}

/** Fetch a short-lived WS token from the backend and return a ready-to-use WS URL. */
export async function getWsChatUrl(): Promise<string> {
  return getWsTokenUrl('/ws/chat')
}

/** Fetch a short-lived WS token from the backend and return a ready-to-use run WS URL. */
export async function getWsRunsUrl(): Promise<string> {
  return getWsTokenUrl('/ws/runs')
}

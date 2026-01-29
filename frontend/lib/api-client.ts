'use client'

/**
 * Unified API Client
 *
 * All frontend API requests should use this module to ensure:
 * - Unified URL construction rules
 * - Unified CSRF Token handling
 * - Unified 401 auto-refresh
 * - Unified error handling
 *
 * @example
 * ```ts
 * import { apiGet, apiPost, apiStream } from '@/lib/api-client'
 *
 * // GET request
 * const users = await apiGet<User[]>('users')
 *
 * // POST request
 * const user = await apiPost<User>('users', { name: 'John' })
 *
 * // SSE streaming request
 * const response = await apiStream('chat/stream', { message: 'Hello' })
 * ```
 */

import { env as runtimeEnv } from 'next-runtime-env'

import { getCsrfToken } from '@/lib/auth/csrf'

// ==================== Configuration ====================
const getBaseUrl = (): string => {
  const url = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  return url?.replace(/\/api\/?$/, '') || 'http://localhost:8000'
}

/** API base URL (without version) */
export const API_BASE_URL = `${getBaseUrl()}/api`
/** API version */
export const API_VERSION = 'v1'
/** Complete API base path */
export const API_BASE = `${API_BASE_URL}/${API_VERSION}`

/** Common endpoint constants (simplify path concatenation) */
export const API_ENDPOINTS = {
  auth: 'auth',
  workspaces: 'workspaces',
  folders: 'folders',
  workflows: 'workflows',
  agents: 'agents',
  graphs: 'graphs',
  chat: 'chat',
  studio: 'studio',
  toolsets: 'toolsets',
  knowledgebases: 'knowledgebases',
  environments: 'environments',
  users: 'users',
  conversations: 'conversations',
  skills: 'skills',
} as const

// ==================== Types ====================
export interface ApiResponse<T> {
  success: boolean
  code: number
  message: string
  data: T
  timestamp?: string
}

export class ApiError extends Error {
  /** Error code, used to identify specific error types (e.g., 'EMAIL_NOT_VERIFIED', 'BAD_REQUEST') */
  public readonly code?: string
  
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly detail?: string,
    code?: string
  ) {
    super(detail || statusText || `API Error: ${status}`)
    this.name = 'ApiError'
    this.code = code || statusText
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  /** Whether to include authentication (default true) */
  withAuth?: boolean
  /** Request body */
  body?: any
  /** Whether it's a JSON request (default true) */
  json?: boolean
  /** Timeout in milliseconds (default 30000) */
  timeout?: number
}

// ==================== Internal Utilities ====================

/** Build complete URL */
function buildUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `${API_BASE}/${path.replace(/^\/+/, '')}`
}

/** Parse response */
async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text()
  if (!text) return undefined as T

  try {
    const json = JSON.parse(text)
    
    // Standard API response format
    if (json && typeof json === 'object' && 'success' in json && 'data' in json) {
      if (!json.success) {
        throw new ApiError(response.status, response.statusText, json.message || 'API request failed', json.code)
      }
      return json.data
    }
    
    return json as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    return text as unknown as T
  }
}

// ==================== Token Refresh ====================
let isRefreshing = false
let refreshPromise: Promise<void> | null = null

export async function refreshAccessTokenOrRelogin(timeout = 10000): Promise<void> {
  if (typeof window === 'undefined') {
    throw new Error('Cannot refresh token in server environment')
  }

  if (isRefreshing && refreshPromise) {
    return refreshPromise
  }

  isRefreshing = true
  refreshPromise = (async () => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), timeout)
    
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
      })
      
      clearTimeout(timeoutId)
      
      if (response.status === 401) {
        throw new Error('Refresh token expired, please login again')
      }
      
      if (!response.ok) {
        throw new Error(`Token refresh failed: ${response.statusText}`)
      }
    } catch (error) {
      clearTimeout(timeoutId)
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('Token refresh timed out')
      }
      throw error
    } finally {
      isRefreshing = false
      refreshPromise = null
    }
  })()

  return refreshPromise
}

// ==================== Core API Methods ====================

/**
 * Unified API request
 */
export async function apiFetch<T>(url: string, options: ApiRequestOptions = {}): Promise<T> {
  const {
    withAuth = true,
    body,
    json = true,
    timeout = 30000,
    headers: customHeaders,
    method = 'GET',
    ...restOptions
  } = options

  const headers: Record<string, string> = {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(customHeaders as Record<string, string>),
  }

  if (withAuth) {
    const csrfToken = getCsrfToken()
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken
    }
  }

  const fullUrl = buildUrl(url)
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  const makeRequest = async (): Promise<Response> => {
    try {
      const response = await fetch(fullUrl, {
        ...restOptions,
        method,
        headers,
        body: body ? (json ? JSON.stringify(body) : body) : undefined,
        signal: controller.signal,
        credentials: 'include',
      })

      if (response.status === 401 && withAuth) {
        try {
          await refreshAccessTokenOrRelogin()
          const newCsrfToken = getCsrfToken()
          if (newCsrfToken) headers['X-CSRF-Token'] = newCsrfToken
          return makeRequest()
        } catch {
          // Refresh failed, continue throwing original error
        }
      }

      if (!response.ok) {
        let errorMessage = response.statusText
        let errorCode: string | undefined
        try {
          const errorData = await response.json()
          errorMessage = errorData.detail || errorData.message || errorMessage
          errorCode = errorData.code
        } catch { /* ignore */ }
        throw new ApiError(response.status, response.statusText, errorMessage, errorCode)
      }

      return response
    } catch (e) {
      if (e instanceof ApiError) throw e
      if (e instanceof Error) {
        if (e.name === 'AbortError') {
          throw new ApiError(408, 'Request Timeout', 'Request timed out')
        }
        throw new ApiError(0, 'Network Error', e.message)
      }
      throw new ApiError(0, 'Unknown Error', String(e))
    } finally {
      clearTimeout(timeoutId)
    }
  }

  const response = await makeRequest()
  return parseResponse<T>(response)
}

// ==================== Convenience Methods ====================

export function apiGet<T>(url: string, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'GET' })
}

export function apiPost<T>(url: string, body?: any, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'POST', body })
}

export function apiPut<T>(url: string, body?: any, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'PUT', body })
}

export function apiDelete<T>(url: string, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'DELETE' })
}

export function apiPatch<T>(url: string, body?: any, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'PATCH', body })
}

export async function apiUpload<T>(
  url: string,
  file: File | FormData,
  options?: Omit<ApiRequestOptions, 'method' | 'body' | 'json'>
): Promise<T> {
  const formData = file instanceof FormData ? file : (() => {
    const fd = new FormData()
    fd.append('file', file)
    return fd
  })()

  return apiFetch<T>(url, { ...options, method: 'POST', body: formData, json: false })
}

/**
 * SSE streaming request
 */
export async function apiStream(
  url: string,
  body: any,
  options?: { signal?: AbortSignal; withAuth?: boolean }
): Promise<Response> {
  const { withAuth = true, signal } = options || {}

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  }

  if (withAuth) {
    const csrfToken = getCsrfToken()
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  }

  const fullUrl = buildUrl(url)

  const makeRequest = async (): Promise<Response> => {
    const response = await fetch(fullUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      credentials: 'include',
      signal,
    })

    if (response.status === 401 && withAuth) {
      try {
        await refreshAccessTokenOrRelogin()
        const newCsrfToken = getCsrfToken()
        if (newCsrfToken) headers['X-CSRF-Token'] = newCsrfToken
        return makeRequest()
      } catch { /* ignore */ }
    }

    if (!response.ok) {
      const errorText = await response.text().catch(() => response.statusText)
      throw new ApiError(response.status, response.statusText, errorText)
    }

    return response
  }

  return makeRequest()
}

// ==================== Default Export ====================
export default {
  fetch: apiFetch,
  get: apiGet,
  post: apiPost,
  put: apiPut,
  delete: apiDelete,
  patch: apiPatch,
  upload: apiUpload,
  stream: apiStream,
}

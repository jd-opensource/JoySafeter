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
 * import { apiGet, apiPost } from '@/lib/api-client'
 *
 * // GET request
 * const users = await apiGet<User[]>('users')
 *
 * // POST request
 * const user = await apiPost<User>('users', { name: 'John' })
 * ```
 */

import { env as runtimeEnv } from 'next-runtime-env'

import { getCsrfToken, setCsrfToken } from '@/lib/auth/csrf'
import { publishRefreshCompleted } from '@/lib/auth/session-events'
import { trimConfigStringFields } from '@/lib/utils/url-trim'
import { useProjectStore } from '@/stores/managed/project-store'

// ==================== Error taxonomy ====================
// ApiError field types. Colocated here (api-client is the only consumer) after
// the legacy types/agent-run.ts module was retired in the v1 frontend cleanup.
export type ErrorSource =
  | 'api'
  | 'engine'
  | 'runtime'
  | 'node'
  | 'tool'
  | 'websocket'
  | 'auth'
  | 'validation'
  | 'permission'
  | 'internal'

export type UserAction = 'retry' | 'configure_model' | 'relogin' | 'fix_input' | 'contact_support'

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
/**
 * Managed-context base path. Historically distinct from API_BASE — the
 * codebase used to expose two parallel surfaces, v1 (legacy) and v2
 * (managed). v1 is fully retired now and the surviving surface has been
 * remounted under /api/v1, so both constants point at the same prefix.
 * Kept as a separate export only so existing `MANAGED_API_BASE` import
 * sites don't need to change.
 */
export const MANAGED_API_BASE = `${API_BASE_URL}/${API_VERSION}`

/** Common endpoint constants (simplify path concatenation) */
export const API_ENDPOINTS = {
  auth: 'auth',
  agents: 'agents',
  chat: 'chat',
  environments: 'environments',
  users: 'users',
  skills: 'skills',
  runs: 'runs',
} as const

// ==================== Types ====================
export interface ApiResponse<T> {
  success: boolean
  code: number
  message: string
  data: T
  timestamp?: string
}

export interface ApiErrorPayload {
  code: string
  message: string
  data?: Record<string, unknown> | null
  source?: ErrorSource
  retryable?: boolean
  user_action?: UserAction
  detail?: string
  trace_id?: string
}

export function createApiError(
  status: number,
  statusText: string,
  payload?: ApiErrorPayload,
): ApiError {
  const normalizedPayload: ApiErrorPayload = payload ?? {
    code: status > 0 ? `HTTP_${status}` : 'UNKNOWN_ERROR',
    message: statusText || `API Error: ${status}`,
    data: null,
  }
  return new ApiError(status, statusText, normalizedPayload)
}

export class ApiError extends Error {
  /** Error code, used to identify specific error types (e.g., 'EMAIL_NOT_VERIFIED', 'BAD_REQUEST') */
  public readonly code: string
  public readonly payload: ApiErrorPayload
  public readonly data?: Record<string, unknown> | null
  public readonly source: ErrorSource
  public readonly retryable: boolean
  public readonly userAction?: UserAction
  public readonly traceId?: string
  public readonly detail?: string

  constructor(
    public readonly status: number,
    public readonly statusText: string,
    payload: ApiErrorPayload,
  ) {
    super(payload.message || statusText || `API Error: ${status}`)
    this.name = 'ApiError'
    this.code = payload.code
    this.payload = payload
    this.data = payload.data ?? null
    this.source = payload.source ?? 'internal'
    this.retryable = payload.retryable ?? false
    this.userAction = payload.user_action
    this.traceId = payload.trace_id
    this.detail = payload.detail
  }
}

const UNAUTHORIZED_ERROR_CODES = new Set([
  'HTTP_401',
  'UNAUTHORIZED',
  'JOYSAFETER_UNAUTHORIZED',
  'REFRESH_TOKEN_INVALID',
  'TOKEN_INVALID',
  'BEARER_TOKEN_MISSING',
  'MISSING_CREDENTIALS',
  'USER_INVALID',
])

export function isUnauthorizedApiError(error: unknown): boolean {
  return error instanceof ApiError && UNAUTHORIZED_ERROR_CODES.has(error.code)
}

const MAX_ERROR_TEXT_LENGTH = 1000

function truncateErrorText(text: string): string {
  if (text.length <= MAX_ERROR_TEXT_LENGTH) return text
  return `${text.slice(0, MAX_ERROR_TEXT_LENGTH)}...`
}

function attachResponseTrace(response: Response, payload: ApiErrorPayload): ApiErrorPayload {
  const traceId = response.headers.get('x-trace-id')
  if (!traceId) return payload
  return { ...payload, trace_id: payload.trace_id ?? traceId }
}

export async function extractErrorFromResponse(response: Response): Promise<ApiError> {
  let payload: ApiErrorPayload | undefined
  let text = ''
  try {
    text = await response.text()
    const errorData = JSON.parse(text)
    if (
      errorData &&
      typeof errorData === 'object' &&
      'code' in errorData &&
      'message' in errorData
    ) {
      payload = errorData as ApiErrorPayload
    } else if (errorData && typeof errorData === 'object' && 'detail' in errorData) {
      const detail = typeof errorData.detail === 'string' ? errorData.detail : response.statusText
      payload = {
        code: response.status > 0 ? `HTTP_${response.status}` : 'UNKNOWN_ERROR',
        message: detail || response.statusText || `API Error: ${response.status}`,
        detail,
        data: typeof errorData.detail === 'string' ? null : { detail: errorData.detail as unknown },
      }
    }
  } catch {
    const message = truncateErrorText(text.trim())
    if (message) {
      payload = {
        code: response.status > 0 ? `HTTP_${response.status}` : 'UNKNOWN_ERROR',
        message,
        detail: message,
        data: null,
      }
    }
  }
  return createApiError(
    response.status,
    response.statusText,
    payload ? attachResponseTrace(response, payload) : payload,
  )
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  /** Whether to include authentication (default true) */
  withAuth?: boolean
  /** Request body */
  body?: unknown
  /** Whether it's a JSON request (default true) */
  json?: boolean
  /** Timeout in milliseconds (default 30000) */
  timeout?: number
  /** Skip persisted managed org/project headers for auth bootstrap requests */
  skipManagedContext?: boolean
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

    if (
      json &&
      typeof json === 'object' &&
      'code' in json &&
      'message' in json &&
      !('success' in json)
    ) {
      throw createApiError(
        response.status,
        response.statusText,
        attachResponseTrace(response, json as ApiErrorPayload),
      )
    }

    if (json && typeof json === 'object' && 'data' in json && 'success' in json) {
      // Paginated response: keep has_more/first_id/last_id alongside data
      if ('has_more' in json) {
        return {
          data: json.data,
          has_more: json.has_more,
          first_id: json.first_id,
          last_id: json.last_id,
        } as T
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
const AUTH_REFRESH_LOCK_KEY = 'auth_refresh_lock'
const AUTH_REFRESHED_AT_KEY = 'auth_refresh_completed_at'
const AUTH_REFRESH_LOCK_TTL_MS = 15_000
const AUTH_REFRESH_LOCK_WAIT_STEP_MS = 150

const authRefreshOwner = `${Date.now()}-${Math.random().toString(36).slice(2)}`

type RefreshLock = {
  owner: string
  expiresAt: number
}

function readRefreshLock(): RefreshLock | null {
  try {
    const raw = localStorage.getItem(AUTH_REFRESH_LOCK_KEY)
    if (!raw) return null
    const lock = JSON.parse(raw) as Partial<RefreshLock>
    if (!lock.owner || typeof lock.expiresAt !== 'number') {
      localStorage.removeItem(AUTH_REFRESH_LOCK_KEY)
      return null
    }
    if (lock.expiresAt <= Date.now()) {
      localStorage.removeItem(AUTH_REFRESH_LOCK_KEY)
      return null
    }
    return { owner: lock.owner, expiresAt: lock.expiresAt }
  } catch {
    return null
  }
}

function tryAcquireRefreshLock(): boolean {
  if (typeof window === 'undefined') return true

  try {
    const current = readRefreshLock()
    if (current && current.owner !== authRefreshOwner) {
      return false
    }

    const lock: RefreshLock = {
      owner: authRefreshOwner,
      expiresAt: Date.now() + AUTH_REFRESH_LOCK_TTL_MS,
    }
    localStorage.setItem(AUTH_REFRESH_LOCK_KEY, JSON.stringify(lock))
    return readRefreshLock()?.owner === authRefreshOwner
  } catch {
    return true
  }
}

function releaseRefreshLock(): void {
  if (typeof window === 'undefined') return
  try {
    if (readRefreshLock()?.owner === authRefreshOwner) {
      localStorage.removeItem(AUTH_REFRESH_LOCK_KEY)
    }
  } catch {
    /* ignore */
  }
}

function getLastRefreshCompletedAt(): number {
  try {
    return Number(localStorage.getItem(AUTH_REFRESHED_AT_KEY) || 0)
  } catch {
    return 0
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function getAbortReason(signal: AbortSignal): unknown {
  return 'reason' in signal ? signal.reason : undefined
}

function createRequestAbortSignal(
  timeout: number,
  externalSignal?: AbortSignal | null,
): {
  signal: AbortSignal
  didTimeout: () => boolean
  cleanup: () => void
} {
  const controller = new AbortController()
  let timedOut = false

  const timeoutId = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)

  const abortFromExternal = () => {
    controller.abort(externalSignal ? getAbortReason(externalSignal) : undefined)
  }

  if (externalSignal?.aborted) {
    abortFromExternal()
  } else {
    externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
  }

  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    cleanup: () => {
      clearTimeout(timeoutId)
      externalSignal?.removeEventListener('abort', abortFromExternal)
    },
  }
}

async function waitForRefreshLockRelease(startedAt: number, timeout: number): Promise<boolean> {
  const deadline = Date.now() + timeout

  while (Date.now() < deadline) {
    if (getLastRefreshCompletedAt() >= startedAt) {
      return true
    }
    if (!readRefreshLock()) {
      return getLastRefreshCompletedAt() >= startedAt
    }
    await sleep(AUTH_REFRESH_LOCK_WAIT_STEP_MS)
  }

  return getLastRefreshCompletedAt() >= startedAt
}

export async function refreshAccessTokenOrRelogin(timeout = 10000): Promise<void> {
  if (typeof window === 'undefined') {
    throw createApiError(500, 'Server Environment Unsupported', {
      code: 'REFRESH_UNAVAILABLE',
      message: 'Cannot refresh token in server environment',
      data: null,
    })
  }

  if (isRefreshing && refreshPromise) {
    return refreshPromise
  }

  isRefreshing = true
  refreshPromise = (async () => {
    const startedAt = Date.now()
    let lockAcquired = tryAcquireRefreshLock()
    if (!lockAcquired) {
      const refreshedByOtherTab = await waitForRefreshLockRelease(startedAt, timeout)
      if (refreshedByOtherTab) {
        return
      }
      lockAcquired = tryAcquireRefreshLock()
    }

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), timeout)

    try {
      if (!lockAcquired) {
        throw createApiError(408, 'Request Timeout', {
          code: 'REFRESH_LOCK_TIMEOUT',
          message: 'Timed out waiting for token refresh',
          data: null,
        })
      }

      const response = await fetch(`${MANAGED_API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      if (response.status === 401) {
        throw createApiError(401, 'Unauthorized', {
          code: 'REFRESH_TOKEN_INVALID',
          message: 'Refresh token expired, please login again',
          data: null,
        })
      }

      if (!response.ok) {
        throw await extractErrorFromResponse(response)
      }

      try {
        const payload = await response.clone().json()
        const csrfToken =
          payload && typeof payload === 'object' && 'data' in payload
            ? payload.data?.csrf_token
            : payload?.csrf_token
        if (typeof csrfToken === 'string' && csrfToken) {
          setCsrfToken(csrfToken)
        }
      } catch {
        /* refresh response without JSON body */
      }
      publishRefreshCompleted(AUTH_REFRESHED_AT_KEY)
    } catch (error) {
      clearTimeout(timeoutId)
      if (error instanceof Error && error.name === 'AbortError') {
        throw createApiError(408, 'Request Timeout', {
          code: 'REQUEST_TIMEOUT',
          message: 'Token refresh timed out',
          data: null,
        })
      }
      if (error instanceof ApiError) throw error
      throw error
    } finally {
      if (lockAcquired) {
        releaseRefreshLock()
      }
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
    skipManagedContext,
    headers: customHeaders,
    method = 'GET',
    signal: externalSignal,
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
    if (!skipManagedContext) {
      const { currentOrgId, currentProjectId } = useProjectStore.getState()
      if (currentOrgId && !headers['X-Org-Id']) {
        headers['X-Org-Id'] = currentOrgId
      }
      if (currentProjectId && !headers['X-Project-Id']) {
        headers['X-Project-Id'] = currentProjectId
      }
    }
  }

  const fullUrl = buildUrl(url)
  const requestSignal = createRequestAbortSignal(timeout, externalSignal)
  let didRefresh = false
  const requestBody = json ? trimConfigStringFields(body) : body

  const makeRequest = async (): Promise<Response> => {
    try {
      const response = await fetch(fullUrl, {
        ...restOptions,
        method,
        headers,
        body:
          body !== undefined
            ? json
              ? JSON.stringify(requestBody)
              : (body as BodyInit)
            : undefined,
        signal: requestSignal.signal,
        credentials: 'include',
      })

      if (response.status === 401 && withAuth && !didRefresh) {
        try {
          didRefresh = true
          await refreshAccessTokenOrRelogin()
          const newCsrfToken = getCsrfToken()
          if (newCsrfToken) headers['X-CSRF-Token'] = newCsrfToken
          return makeRequest()
        } catch (refreshError) {
          if (!isUnauthorizedApiError(refreshError)) {
            throw refreshError
          }
          // Refresh token is invalid/expired, continue throwing original 401.
        }
      }

      if (!response.ok) {
        throw await extractErrorFromResponse(response)
      }

      return response
    } catch (e) {
      if (e instanceof ApiError) throw e
      if (e instanceof Error) {
        if (e.name === 'AbortError') {
          if (requestSignal.didTimeout()) {
            throw createApiError(408, 'Request Timeout', {
              code: 'REQUEST_TIMEOUT',
              message: 'Request timed out',
              data: null,
            })
          }
          throw createApiError(0, 'Request Aborted', {
            code: 'REQUEST_ABORTED',
            message: 'Request was aborted',
            data: null,
          })
        }
        throw createApiError(0, 'Network Error', {
          code: 'NETWORK_ERROR',
          message: e.message,
          data: null,
        })
      }
      throw createApiError(0, 'Unknown Error', {
        code: 'UNKNOWN_ERROR',
        message: String(e),
        data: null,
      })
    } finally {
      requestSignal.cleanup()
    }
  }

  const response = await makeRequest()
  return parseResponse<T>(response)
}

export async function apiFetchResponse(
  url: string,
  options: ApiRequestOptions = {},
): Promise<Response> {
  const {
    withAuth = true,
    body,
    json = true,
    timeout = 30000,
    skipManagedContext,
    headers: customHeaders,
    method = 'GET',
    signal: externalSignal,
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
    if (!skipManagedContext) {
      const { currentOrgId, currentProjectId } = useProjectStore.getState()
      if (currentOrgId && !headers['X-Org-Id']) {
        headers['X-Org-Id'] = currentOrgId
      }
      if (currentProjectId && !headers['X-Project-Id']) {
        headers['X-Project-Id'] = currentProjectId
      }
    }
  }

  const fullUrl = buildUrl(url)
  const requestSignal = createRequestAbortSignal(timeout, externalSignal)
  let didRefresh = false
  const requestBody = json ? trimConfigStringFields(body) : body

  const makeRequest = async (): Promise<Response> => {
    try {
      const response = await fetch(fullUrl, {
        ...restOptions,
        method,
        headers,
        body:
          body !== undefined
            ? json
              ? JSON.stringify(requestBody)
              : (body as BodyInit)
            : undefined,
        signal: requestSignal.signal,
        credentials: 'include',
      })

      if (response.status === 401 && withAuth && !didRefresh) {
        try {
          didRefresh = true
          await refreshAccessTokenOrRelogin()
          const newCsrfToken = getCsrfToken()
          if (newCsrfToken) headers['X-CSRF-Token'] = newCsrfToken
          return makeRequest()
        } catch (refreshError) {
          if (!isUnauthorizedApiError(refreshError)) {
            throw refreshError
          }
        }
      }

      if (!response.ok) {
        throw await extractErrorFromResponse(response)
      }

      return response
    } catch (e) {
      if (e instanceof ApiError) throw e
      if (e instanceof Error) {
        if (e.name === 'AbortError') {
          if (requestSignal.didTimeout()) {
            throw createApiError(408, 'Request Timeout', {
              code: 'REQUEST_TIMEOUT',
              message: 'Request timed out',
              data: null,
            })
          }
          throw createApiError(0, 'Request Aborted', {
            code: 'REQUEST_ABORTED',
            message: 'Request was aborted',
            data: null,
          })
        }
        throw createApiError(0, 'Network Error', {
          code: 'NETWORK_ERROR',
          message: e.message,
          data: null,
        })
      }
      throw createApiError(0, 'Unknown Error', {
        code: 'UNKNOWN_ERROR',
        message: String(e),
        data: null,
      })
    } finally {
      requestSignal.cleanup()
    }
  }

  return makeRequest()
}

// ==================== Convenience Methods ====================

export function apiGet<T>(
  url: string,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'GET' })
}

export function apiPost<T>(
  url: string,
  body?: unknown,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'POST', body })
}

export function apiPut<T>(
  url: string,
  body?: unknown,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'PUT', body })
}

export function apiDelete<T>(
  url: string,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'DELETE' })
}

export function apiPatch<T>(
  url: string,
  body?: unknown,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  return apiFetch<T>(url, { ...options, method: 'PATCH', body })
}

export async function apiUpload<T>(
  url: string,
  file: File | FormData,
  options?: Omit<ApiRequestOptions, 'method' | 'body' | 'json'>,
): Promise<T> {
  const formData =
    file instanceof FormData
      ? file
      : (() => {
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
  body: unknown,
  options?: {
    signal?: AbortSignal
    withAuth?: boolean
    skipManagedContext?: boolean
    headers?: HeadersInit
  },
): Promise<Response> {
  const { withAuth = true, signal, skipManagedContext, headers: customHeaders } = options || {}

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...(customHeaders as Record<string, string>),
  }

  if (withAuth) {
    const csrfToken = getCsrfToken()
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken
    if (!skipManagedContext) {
      const { currentProjectId, currentOrgId } = useProjectStore.getState()
      if (currentOrgId) headers['X-Org-Id'] = currentOrgId
      if (currentProjectId) headers['X-Project-Id'] = currentProjectId
    }
  }

  const fullUrl = buildUrl(url)
  let didRefresh = false

  const makeRequest = async (): Promise<Response> => {
    const response = await fetch(fullUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      credentials: 'include',
      signal,
    })

    if (response.status === 401 && withAuth && !didRefresh) {
      try {
        didRefresh = true
        await refreshAccessTokenOrRelogin()
        const newCsrfToken = getCsrfToken()
        if (newCsrfToken) headers['X-CSRF-Token'] = newCsrfToken
        return makeRequest()
      } catch (refreshError) {
        if (!isUnauthorizedApiError(refreshError)) {
          throw refreshError
        }
        /* Refresh token is invalid/expired, continue throwing original 401. */
      }
    }

    if (!response.ok) {
      throw await extractErrorFromResponse(response)
    }

    return response
  }

  return makeRequest()
}

// ==================== Managed JoySafeter API Methods ====================

function buildManagedUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `${MANAGED_API_BASE}/${path.replace(/^\/+/, '')}`
}

function getManagedHeaders(
  customHeaders?: Record<string, string>,
  skipManagedContext = false,
): Record<string, string> {
  const { currentProjectId, currentOrgId } = useProjectStore.getState()
  const headers: Record<string, string> = { ...customHeaders }
  if (skipManagedContext) {
    return headers
  }
  if (currentOrgId && !headers['X-Org-Id']) {
    headers['X-Org-Id'] = currentOrgId
  }
  if (currentProjectId && !headers['X-Project-Id']) {
    headers['X-Project-Id'] = currentProjectId
  }
  return headers
}

export function managedGet<T>(
  url: string,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiFetch<T>(buildManagedUrl(url), { ...options, headers, method: 'GET' })
}

export function managedPost<T>(
  url: string,
  body?: unknown,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiFetch<T>(buildManagedUrl(url), { ...options, headers, method: 'POST', body })
}

export function managedPut<T>(
  url: string,
  body?: unknown,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiFetch<T>(buildManagedUrl(url), { ...options, headers, method: 'PUT', body })
}

export function managedDelete<T>(
  url: string,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiFetch<T>(buildManagedUrl(url), { ...options, headers, method: 'DELETE' })
}

export function managedPatch<T>(
  url: string,
  body?: unknown,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<T> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiFetch<T>(buildManagedUrl(url), { ...options, headers, method: 'PATCH', body })
}

export function managedUpload<T>(
  url: string,
  file: File | FormData,
  options?: Omit<ApiRequestOptions, 'method' | 'body' | 'json'>,
): Promise<T> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiUpload<T>(buildManagedUrl(url), file, { ...options, headers })
}

export function managedFetchResponse(
  url: string,
  options?: Omit<ApiRequestOptions, 'method' | 'body'>,
): Promise<Response> {
  const headers = getManagedHeaders(
    options?.headers as Record<string, string>,
    options?.skipManagedContext,
  )
  return apiFetchResponse(buildManagedUrl(url), { ...options, headers, method: 'GET' })
}

// ==================== Default Export ====================
const apiClient = {
  fetch: apiFetch,
  get: apiGet,
  post: apiPost,
  put: apiPut,
  delete: apiDelete,
  patch: apiPatch,
  upload: apiUpload,
  stream: apiStream,
  response: apiFetchResponse,
}

export default apiClient

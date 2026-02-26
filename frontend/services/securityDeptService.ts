'use client'

import { API_BASE, ApiError, apiGet, apiPost } from '@/lib/api-client'
import { getCsrfToken } from '@/lib/auth/csrf'

export type SecurityDeptTaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface SecurityDeptTask {
  id: string
  user_id: string
  workspace_id: string | null
  scenario: string
  profile: string
  status: SecurityDeptTaskStatus
  target: string | null
  instruction_preview: string
  selected_skills: string[]
  summary_md: string | null
  error_code: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  token_usage: Record<string, unknown> | null
  cost_usd: number | null
  execution_stats: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface SecurityDeptTaskListResponse {
  items: SecurityDeptTask[]
  total: number
  page: number
  page_size: number
}

export interface SecurityDeptCreateTaskRequest {
  scenario: 'pentest'
  target?: string
  instruction: string
  skill_names?: string[]
  workspace_id?: string
  profile?: string
}

export interface SecurityDeptCreateTaskResponse {
  task_id: string
  status: SecurityDeptTaskStatus
  created_at: string
}

export interface SecurityDeptCancelTaskResponse {
  task_id: string
  status: SecurityDeptTaskStatus
}

export interface SecurityDeptProfile {
  name: string
  description: string
  permission_mode: string
  scenario: string
}

export interface SecurityDeptSkill {
  skill_name: string
  display_name: string
  description: string
  has_skill_md: boolean
  abs_path: string
}

export interface SecurityDeptSkillsResponse {
  items: SecurityDeptSkill[]
  root_path: string
}

export interface SecurityDeptHealthResponse {
  enabled: boolean
  redis_available: boolean
  sdk_installed: boolean
  cli_found: boolean
  configured_cli_path: string | null
  max_concurrent_tasks: number
  timeout_seconds: number
  workdir_root: string
}

export interface SecurityDeptStreamEvent {
  type: string
  task_id: string
  timestamp: number
  data: Record<string, unknown>
}

export interface StreamTaskEventsOptions {
  taskId: string
  signal?: AbortSignal
  onEvent: (event: SecurityDeptStreamEvent) => void
  onError?: (error: Error) => void
}

function parseSseChunk(chunk: string): SecurityDeptStreamEvent[] {
  const events: SecurityDeptStreamEvent[] = []
  const lines = chunk.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('data:')) {
      continue
    }
    const payload = trimmed.slice('data:'.length).trim()
    if (!payload) {
      continue
    }
    try {
      const parsed = JSON.parse(payload)
      if (parsed && typeof parsed === 'object' && parsed.type && parsed.task_id) {
        events.push(parsed as SecurityDeptStreamEvent)
      }
    } catch {
      // Ignore malformed chunks.
    }
  }
  return events
}

export async function streamTaskEvents(options: StreamTaskEventsOptions): Promise<void> {
  const { taskId, signal, onEvent, onError } = options
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
  }
  const csrfToken = getCsrfToken()
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken
  }

  try {
    const response = await fetch(`${API_BASE}/security-dept/tasks/${taskId}/events`, {
      method: 'GET',
      credentials: 'include',
      headers,
      signal,
    })
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText, 'Failed to open task event stream')
    }
    if (!response.body) {
      throw new ApiError(500, 'Empty Body', 'SSE stream body is empty')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) {
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          const events = parseSseChunk(part)
          for (const event of events) {
            onEvent(event)
            if (event.type === 'done') {
              return
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  } catch (error) {
    if (signal?.aborted) {
      return
    }
    if (onError) {
      onError(error instanceof Error ? error : new Error(String(error)))
    }
  }
}

export const securityDeptService = {
  getHealth: () => apiGet<SecurityDeptHealthResponse>('security-dept/health'),
  listProfiles: async (): Promise<SecurityDeptProfile[]> => {
    const response = await apiGet<{ items: SecurityDeptProfile[] }>('security-dept/profiles')
    return response.items || []
  },
  listSkills: () => apiGet<SecurityDeptSkillsResponse>('security-dept/skills/fs'),
  createTask: (payload: SecurityDeptCreateTaskRequest) =>
    apiPost<SecurityDeptCreateTaskResponse>('security-dept/tasks', payload),
  listTasks: (params?: { page?: number; page_size?: number; status?: string }) => {
    const query = new URLSearchParams()
    if (params?.page) query.set('page', String(params.page))
    if (params?.page_size) query.set('page_size', String(params.page_size))
    if (params?.status) query.set('status', params.status)
    const suffix = query.toString()
    return apiGet<SecurityDeptTaskListResponse>(`security-dept/tasks${suffix ? `?${suffix}` : ''}`)
  },
  getTask: (taskId: string) => apiGet<SecurityDeptTask>(`security-dept/tasks/${taskId}`),
  cancelTask: (taskId: string) => apiPost<SecurityDeptCancelTaskResponse>(`security-dept/tasks/${taskId}/cancel`, {}),
  streamTaskEvents,
}

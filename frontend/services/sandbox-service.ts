import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api-client'

export interface Sandbox {
  id: string
  user_id: string
  container_id?: string
  status: string
  image: string
  runtime?: string
  last_active_at?: string
  error_message?: string
  cpu_limit?: number
  memory_limit?: number
  idle_timeout: number
  created_at: string
  updated_at: string
  user?: {
    name: string
    email: string
  }
}

export interface SandboxListResponse {
  items: Sandbox[]
  total: number
  page: number
  size: number
  pages: number
}

export const sandboxService = {
  async listSandboxes(page = 1, size = 20, status?: string): Promise<SandboxListResponse> {
    const params = new URLSearchParams({
      page: page.toString(),
      size: size.toString(),
    })
    if (status && status !== 'all') {
      params.append('status', status)
    }

    return apiGet<SandboxListResponse>(`sandboxes?${params.toString()}`)
  },

  async stopSandbox(id: string): Promise<void> {
    await apiPost(`sandboxes/${id}/stop`)
  },

  async restartSandbox(id: string): Promise<void> {
    await apiPost(`sandboxes/${id}/restart`)
  },

  async rebuildSandbox(id: string): Promise<void> {
    await apiPost(`sandboxes/${id}/rebuild`)
  },

  async deleteSandbox(id: string): Promise<void> {
    await apiDelete(`sandboxes/${id}`)
  },

  async updateSandbox(id: string, payload: { image?: string }): Promise<void> {
    await apiPatch(`sandboxes/${id}`, payload)
  },
}

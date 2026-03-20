'use client'

/**
 * API Key Service
 *
 * Frontend service for managing workspace API keys.
 * Calls backend /api/v1/api-keys endpoints.
 */

import { apiGet, apiPost, apiFetch } from '@/lib/api-client'

// ==================== Types ====================

export interface ApiKey {
  id: string
  name: string
  key: string // full key for copying
  keyMasked: string // masked key for display
  type: 'personal' | 'workspace'
  workspaceId: string | null
  createdAt: string
  expiresAt: string | null
  lastUsed: string | null
}

export interface CreateApiKeyResponse {
  id: string
  name: string
  key: string // full key, shown only once
  type: string
  workspaceId: string | null
  createdAt: string
}

// ==================== Service ====================

export const apiKeyService = {
  /**
   * List API keys for a workspace
   */
  async listKeys(workspaceId: string): Promise<ApiKey[]> {
    return apiGet<ApiKey[]>(`api-keys?workspaceId=${workspaceId}`)
  },

  /**
   * Create a new API key
   */
  async createKey(params: {
    name: string
    type: 'personal' | 'workspace'
    workspaceId?: string
    expiresInDays?: number
  }): Promise<CreateApiKeyResponse> {
    let expiresAt: string | undefined
    if (params.expiresInDays) {
      const d = new Date()
      d.setDate(d.getDate() + params.expiresInDays)
      expiresAt = d.toISOString()
    }
    return apiPost<CreateApiKeyResponse>('api-keys', {
      name: params.name,
      type: params.type,
      workspaceId: params.workspaceId,
      expiresAt,
    })
  },

  /**
   * Delete an API key
   */
  async deleteKey(keyId: string): Promise<void> {
    return apiFetch<void>(`api-keys/${keyId}`, { method: 'DELETE' })
  },
}

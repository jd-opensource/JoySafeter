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
  key: string          // masked, except on creation
  type: 'personal' | 'workspace'
  workspace_id: string | null
  created_at: string
  expires_at: string | null
  last_used: string | null
}

export interface CreateApiKeyResponse {
  id: string
  name: string
  key: string          // full key, shown only once
  type: string
  workspace_id: string | null
  created_at: string
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
    return apiPost<CreateApiKeyResponse>('api-keys', {
      name: params.name,
      type: params.type,
      workspaceId: params.workspaceId,
      expiresInDays: params.expiresInDays,
    })
  },

  /**
   * Delete an API key
   */
  async deleteKey(keyId: string): Promise<void> {
    return apiFetch<void>(`api-keys/${keyId}`, { method: 'DELETE' })
  },
}

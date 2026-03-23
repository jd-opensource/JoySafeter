import { apiGet, apiPost, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export interface PlatformToken {
  id: string
  name: string
  tokenPrefix: string
  scopes: string[]
  resourceType: 'skill' | 'graph' | 'tool' | null
  resourceId: string | null
  expiresAt: string | null
  lastUsedAt: string | null
  isActive: boolean
  createdAt: string | null
}

export interface PlatformTokenCreateResponse {
  id: string
  name: string
  token: string
  tokenPrefix: string
  scopes: string[]
  resourceType: 'skill' | 'graph' | 'tool' | null
  expiresAt: string | null
  createdAt: string | null
}

export interface TokenCreateRequest {
  name: string
  scopes: string[]
  expires_at?: string | null
  resource_type?: string | null
  resource_id?: string | null
}

// ---------- Normalizers ----------

function normalizeToken(raw: any): PlatformToken {
  return {
    id: raw.id,
    name: raw.name,
    tokenPrefix: raw.token_prefix,
    scopes: raw.scopes ?? [],
    resourceType: raw.resource_type ?? null,
    resourceId: raw.resource_id ?? null,
    expiresAt: raw.expires_at ?? null,
    lastUsedAt: raw.last_used_at ?? null,
    isActive: raw.is_active ?? true,
    createdAt: raw.created_at ?? null,
  }
}

function normalizeTokenCreateResponse(raw: any): PlatformTokenCreateResponse {
  return {
    id: raw.id,
    name: raw.name,
    token: raw.token,
    tokenPrefix: raw.token_prefix,
    scopes: raw.scopes ?? [],
    resourceType: raw.resource_type ?? null,
    expiresAt: raw.expires_at ?? null,
    createdAt: raw.created_at ?? null,
  }
}

export interface TokenListParams {
  resourceType?: 'skill' | 'graph' | 'tool'
  resourceId?: string
}

export const platformTokenService = {
  async listTokens(params?: TokenListParams): Promise<PlatformToken[]> {
    const queryParams = new URLSearchParams()
    if (params?.resourceType) queryParams.set('resource_type', params.resourceType)
    if (params?.resourceId) queryParams.set('resource_id', params.resourceId)

    const url = `tokens${queryParams.toString() ? `?${queryParams}` : ''}`
    const data = await apiGet<any[]>(url)
    return (Array.isArray(data) ? data : []).map(normalizeToken)
  },

  async createToken(payload: TokenCreateRequest): Promise<PlatformTokenCreateResponse> {
    const data = await apiPost<any>('tokens', payload)
    return normalizeTokenCreateResponse(data)
  },

  async revokeToken(tokenId: string): Promise<void> {
    await apiDelete<any>(`tokens/${tokenId}`)
  },
}

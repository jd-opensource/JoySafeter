import { apiGet, apiPost, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export interface PlatformToken {
  id: string
  name: string
  tokenPrefix: string
  scopes: string[]
  resourceType: string | null
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
  expiresAt: string | null
}

export interface TokenCreateRequest {
  name: string
  scopes: string[]
  expires_at?: string | null
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
    expiresAt: raw.expires_at ?? null,
  }
}

// ---------- Service ----------

export const platformTokenService = {
  async listTokens(): Promise<PlatformToken[]> {
    const data = await apiGet<any[]>('tokens')
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

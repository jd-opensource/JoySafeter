import { describe, expect, it } from 'vitest'

import {
  apiKeyStatusLabelKey,
  buildApiKeyCreatePayload,
  canRevokeApiKey,
} from './api-key-lifecycle'

describe('API key lifecycle helpers', () => {
  it('preserves the no-expiry compatibility contract', () => {
    expect(buildApiKeyCreatePayload('Deploy', 'viewer', '')).toEqual({
      name: 'Deploy',
      role: 'viewer',
    })
  })

  it('serializes a local expiry as an absolute timestamp', () => {
    const localExpiry = '2026-08-24T12:30'

    expect(buildApiKeyCreatePayload('Deploy', 'editor', localExpiry)).toEqual({
      name: 'Deploy',
      role: 'editor',
      expires_at: new Date(localExpiry).toISOString(),
    })
  })

  it('maps status labels and prevents repeated revocation', () => {
    expect(apiKeyStatusLabelKey('expired')).toBe('manage.apiKeys.status.expired')
    expect(canRevokeApiKey('active')).toBe(true)
    expect(canRevokeApiKey('expired')).toBe(true)
    expect(canRevokeApiKey('revoked')).toBe(false)
  })
})

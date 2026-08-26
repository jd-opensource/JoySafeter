import { describe, expect, it } from 'vitest'

import { parseApiKeyCreateResponse, parseApiKeyResponse } from './api-key-response-parsers'

const API_KEY_ID = 'apikey_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030'
const PROJECT_ID = 'proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'

function apiKeyResponse() {
  return {
    id: API_KEY_ID,
    project_id: PROJECT_ID,
    name: 'Deploy key',
    key_prefix: 'jsk_live_1234',
    role: 'viewer',
    status: 'active',
    created_at: '2026-08-26T00:00:00Z',
    expires_at: null,
    revoked_at: null,
    last_used_at: null,
  }
}

describe('API key response parsers', () => {
  it('brands canonical API key and project IDs', () => {
    expect(parseApiKeyResponse(apiKeyResponse())).toMatchObject({
      id: API_KEY_ID,
      project_id: PROJECT_ID,
      status: 'active',
    })
  })

  it.each([
    {},
    { ...apiKeyResponse(), id: '018f6f42-0a51-7cc4-98c8-4f6f0ca5f030' },
    { ...apiKeyResponse(), id: PROJECT_ID },
    { ...apiKeyResponse(), project_id: API_KEY_ID },
  ])('rejects malformed API key responses', (response) => {
    expect(() => parseApiKeyResponse(response)).toThrow()
  })

  it('requires the one-time raw key on create responses', () => {
    expect(() => parseApiKeyCreateResponse(apiKeyResponse())).toThrow()
    expect(parseApiKeyCreateResponse({ ...apiKeyResponse(), raw_key: 'jsk_secret' }).raw_key).toBe(
      'jsk_secret',
    )
  })
})

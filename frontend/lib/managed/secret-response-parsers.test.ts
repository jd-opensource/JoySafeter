import { describe, expect, it } from 'vitest'

import {
  parseSecretDetailResponse,
  parseSecretListResponse,
  parseSecretResponse,
} from './secret-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'

const rawSecret = () => ({
  id: `secret_${UUID}`,
  name: 'openai-prod',
  provider: 'openai',
  protocol: 'openai',
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('secret response parsers', () => {
  it('parses list and detail IDs at the API boundary', () => {
    expect(parseSecretResponse(rawSecret()).id).toBe(`secret_${UUID}`)
    expect(parseSecretListResponse([rawSecret()])[0].id).toBe(`secret_${UUID}`)
    expect(
      parseSecretDetailResponse({ ...rawSecret(), secret_data: { API_KEY: '********' } }).id,
    ).toBe(`secret_${UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseSecretResponse({ ...rawSecret(), id: UUID })).toThrow()
    expect(() => parseSecretResponse({ ...rawSecret(), id: `env_${UUID}` })).toThrow()
  })
})

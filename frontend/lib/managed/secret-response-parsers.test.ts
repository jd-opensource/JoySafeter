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
  kind: 'llm',
  provider: 'openai',
  protocol: 'openai_responses',
  model: 'gpt-5',
  compatible_engine_ids: ['codex', 'native', 'pi'],
  is_default: true,
  keys: ['OPENAI_API_KEY', 'OPENAI_MODEL'],
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('secret response parsers', () => {
  it('parses list and detail IDs at the API boundary', () => {
    const listSecret = rawSecret()
    const { keys: _keys, ...detailSecret } = listSecret
    expect(parseSecretResponse(listSecret).id).toBe(`secret_${UUID}`)
    expect(parseSecretListResponse([listSecret])[0].id).toBe(`secret_${UUID}`)
    expect(
      parseSecretDetailResponse({ ...detailSecret, secret_data: { API_KEY: '********' } }).id,
    ).toBe(`secret_${UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseSecretResponse({ ...rawSecret(), id: UUID })).toThrow()
    expect(() => parseSecretResponse({ ...rawSecret(), id: `env_${UUID}` })).toThrow()
  })

  it('parses LLM metadata and rejects invalid kinds', () => {
    expect(parseSecretResponse(rawSecret())).toMatchObject({
      kind: 'llm',
      provider: 'openai',
      protocol: 'openai_responses',
      model: 'gpt-5',
      is_default: true,
      compatible_engine_ids: ['codex', 'native', 'pi'],
    })
    expect(() => parseSecretResponse({ ...rawSecret(), kind: 'engine' })).toThrow()
  })

  it('omits blank metadata keys without renaming nonblank field names', () => {
    const listSecret = {
      ...rawSecret(),
      keys: ['', '   ', ' TOKEN ', 'OPENAI_API_KEY'],
    }
    const detailSecret: Record<string, unknown> = { ...listSecret }
    delete detailSecret.keys

    expect(parseSecretResponse(listSecret).keys).toEqual([' TOKEN ', 'OPENAI_API_KEY'])
    expect(
      parseSecretDetailResponse({
        ...detailSecret,
        secret_data: {
          '': '********',
          '   ': '********',
          ' TOKEN ': '********name',
          OPENAI_API_KEY: '********value',
        },
      }).secret_data,
    ).toEqual({
      ' TOKEN ': '********name',
      OPENAI_API_KEY: '********value',
    })
  })
})

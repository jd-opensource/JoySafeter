import { describe, expect, it } from 'vitest'

import {
  filterSelectableSecretResources,
  parseSecretDetailResponse,
  parseSecretListResponse,
  parseSecretResponse,
} from './secret-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'

const rawSecret = () => ({
  id: `cred_${UUID}`,
  name: 'openai-prod',
  kind: 'model',
  provider: 'openai',
  protocol: 'openai_responses',
  model: 'gpt-5',
  compatible_engine_ids: ['codex', 'native', 'pi'],
  is_default: true,
  data: { OPENAI_API_KEY: '********', OPENAI_MODEL: 'gpt-5' },
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('secret response parsers', () => {
  it('parses list and detail IDs at the API boundary', () => {
    const listSecret = rawSecret()
    expect(parseSecretResponse(listSecret).id).toBe(`cred_${UUID}`)
    expect(parseSecretListResponse([listSecret])[0].id).toBe(`cred_${UUID}`)
    expect(parseSecretDetailResponse(listSecret).id).toBe(`cred_${UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseSecretResponse({ ...rawSecret(), id: UUID })).toThrow()
    expect(() => parseSecretResponse({ ...rawSecret(), id: `env_${UUID}` })).toThrow()
  })

  it('parses model metadata and rejects invalid kinds', () => {
    expect(parseSecretResponse(rawSecret())).toMatchObject({
      kind: 'model',
      provider: 'openai',
      protocol: 'openai_responses',
      model: 'gpt-5',
      is_default: true,
      compatible_engine_ids: ['codex', 'native', 'pi'],
    })
    expect(() => parseSecretResponse({ ...rawSecret(), kind: 'engine' })).toThrow()
  })

  it('exposes field names via data and omits blank keys without renaming nonblank fields', () => {
    const detail = parseSecretDetailResponse({
      ...rawSecret(),
      data: {
        '': '********',
        '   ': '********',
        ' TOKEN ': '********name',
        OPENAI_API_KEY: '********value',
      },
    })

    expect(Object.keys(detail.data)).toEqual([' TOKEN ', 'OPENAI_API_KEY'])
    expect(detail.data).toEqual({
      ' TOKEN ': '********name',
      OPENAI_API_KEY: '********value',
    })
  })

  it('preserves historical resource names for management while filtering selector inputs', () => {
    const historicalSecrets = parseSecretListResponse([
      { ...rawSecret(), name: '' },
      { ...rawSecret(), name: '   ' },
      { ...rawSecret(), name: ' padded-name ' },
      { ...rawSecret(), name: 'canonical-name' },
    ])

    expect(historicalSecrets.map((secret) => secret.name)).toEqual([
      '',
      '   ',
      ' padded-name ',
      'canonical-name',
    ])
    expect(filterSelectableSecretResources(historicalSecrets).map((secret) => secret.name)).toEqual([
      'canonical-name',
    ])
  })
})

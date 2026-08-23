import { describe, expect, it } from 'vitest'

import {
  filterSelectableCredentials,
  parseCredentialDetailResponse,
  parseCredentialListResponse,
  parseCredentialResponse,
} from './credential-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'

const rawCredential = () => ({
  id: `cred_${UUID}`,
  name: 'openai-prod',
  kind: 'model',
  provider: 'openai',
  protocol: 'openai_responses',
  model: 'gpt-5',
  compatible_engine_ids: ['codex', 'native', 'pi'],
  is_default: true,
  data: { OPENAI_API_KEY: '********', OPENAI_MODEL: 'gpt-5' },
  archived_at: null,
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('credential response parsers', () => {
  it('parses list and detail IDs at the API boundary', () => {
    const listCredential = rawCredential()
    expect(parseCredentialResponse(listCredential).id).toBe(`cred_${UUID}`)
    expect(parseCredentialListResponse([listCredential])[0].id).toBe(`cred_${UUID}`)
    expect(parseCredentialDetailResponse(listCredential).id).toBe(`cred_${UUID}`)
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseCredentialResponse({ ...rawCredential(), id: UUID })).toThrow()
    expect(() => parseCredentialResponse({ ...rawCredential(), id: `env_${UUID}` })).toThrow()
  })

  it('parses model metadata and rejects invalid kinds', () => {
    expect(parseCredentialResponse(rawCredential())).toMatchObject({
      kind: 'model',
      provider: 'openai',
      protocol: 'openai_responses',
      model: 'gpt-5',
      is_default: true,
      compatible_engine_ids: ['codex', 'native', 'pi'],
      archived_at: null,
    })
    expect(() => parseCredentialResponse({ ...rawCredential(), kind: 'engine' })).toThrow()
  })

  it('exposes field names via data and omits blank keys without renaming nonblank fields', () => {
    const detail = parseCredentialDetailResponse({
      ...rawCredential(),
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
    const historicalCredentials = parseCredentialListResponse([
      { ...rawCredential(), name: '' },
      { ...rawCredential(), name: '   ' },
      { ...rawCredential(), name: ' padded-name ' },
      { ...rawCredential(), name: 'canonical-name' },
    ])

    expect(historicalCredentials.map((credential) => credential.name)).toEqual([
      '',
      '   ',
      ' padded-name ',
      'canonical-name',
    ])
    expect(
      filterSelectableCredentials(historicalCredentials).map((credential) => credential.name),
    ).toEqual(['canonical-name'])
  })
})

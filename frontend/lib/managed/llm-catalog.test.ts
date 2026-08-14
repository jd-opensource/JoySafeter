import { describe, expect, it } from 'vitest'

import {
  findCredentialProfileForBinding,
  getCredentialProfileForBinding,
  getEnabledEngines,
  getProviderProtocolOptions,
  parseLlmCatalogResponse,
  stableConnectionFingerprint,
} from './llm-catalog'

function rawCatalog() {
  return {
    version: '2026-08-07.1',
    protocols: [
      {
        id: 'anthropic_messages',
        display_name: 'Anthropic Messages API',
        description: 'Anthropic contract',
      },
      {
        id: 'openai_responses',
        display_name: 'OpenAI Responses API',
        description: 'Responses contract',
      },
      {
        id: 'chat_completions',
        display_name: 'Chat Completions API',
        description: 'Chat contract',
      },
    ],
    engines: [
      {
        id: 'claude',
        display_name: 'Claude Code',
        enabled: true,
        supported_protocol_ids: ['anthropic_messages'],
        preferred_protocol_ids: ['anthropic_messages'],
      },
      {
        id: 'native',
        display_name: 'Native',
        enabled: true,
        supported_protocol_ids: ['anthropic_messages', 'openai_responses', 'chat_completions'],
        preferred_protocol_ids: ['anthropic_messages', 'openai_responses', 'chat_completions'],
      },
    ],
    credential_profiles: [
      {
        id: 'anthropic_standard',
        fields: [
          { key: 'ANTHROPIC_API_KEY', label: 'API Key', type: 'secret', required: false },
          { key: 'ANTHROPIC_MODEL', label: 'Model', type: 'text', required: false },
        ],
        required_any_of: [['ANTHROPIC_API_KEY']],
        base_url_key: null,
        model_key: 'ANTHROPIC_MODEL',
      },
      {
        id: 'openai_bearer',
        fields: [
          { key: 'OPENAI_API_KEY', label: 'API Key', type: 'secret', required: true },
          { key: 'OPENAI_MODEL', label: 'Model', type: 'text', required: false },
        ],
        required_any_of: [],
        base_url_key: null,
        model_key: 'OPENAI_MODEL',
      },
    ],
    providers: [
      {
        id: 'anthropic',
        display_name: 'Anthropic',
        enabled: true,
        protocol_bindings: [
          {
            protocol_id: 'anthropic_messages',
            credential_profile_id: 'anthropic_standard',
            default_base_url: 'https://api.anthropic.com',
            model_suggestions: ['claude-sonnet-4-5'],
          },
        ],
      },
      {
        id: 'openai',
        display_name: 'OpenAI',
        enabled: true,
        protocol_bindings: [
          {
            protocol_id: 'openai_responses',
            credential_profile_id: 'openai_bearer',
            default_base_url: 'https://api.openai.com/v1',
            model_suggestions: ['gpt-5'],
          },
          {
            protocol_id: 'chat_completions',
            credential_profile_id: 'openai_bearer',
            default_base_url: 'https://api.openai.com/v1',
            model_suggestions: ['gpt-5'],
          },
        ],
      },
    ],
  }
}

describe('LLM catalog helpers', () => {
  it('strictly parses the response and rejects unknown references', () => {
    expect(parseLlmCatalogResponse(rawCatalog()).version).toBe('2026-08-07.1')

    const invalid = rawCatalog()
    invalid.providers[0].protocol_bindings[0].credential_profile_id = 'missing-profile'
    expect(() => parseLlmCatalogResponse(invalid)).toThrow(/missing-profile/)
  })

  it('preserves catalog order while filtering provider and protocol options by engine', () => {
    const catalog = parseLlmCatalogResponse(rawCatalog())

    expect(getProviderProtocolOptions(catalog, 'claude')).toEqual([
      expect.objectContaining({ providerId: 'anthropic', protocolId: 'anthropic_messages' }),
    ])
    expect(
      getProviderProtocolOptions(catalog, 'native').map(
        ({ providerId, protocolId }) => `${providerId}:${protocolId}`,
      ),
    ).toEqual([
      'anthropic:anthropic_messages',
      'openai:openai_responses',
      'openai:chat_completions',
    ])
    expect(getCredentialProfileForBinding(catalog, 'openai', 'chat_completions').id).toBe(
      'openai_bearer',
    )
  })

  it('removes disabled engines from choices and compatibility options', () => {
    const raw = rawCatalog()
    raw.engines[0].enabled = false
    const catalog = parseLlmCatalogResponse(raw)

    expect(getEnabledEngines(catalog).map((engine) => engine.id)).toEqual(['native'])
    expect(getProviderProtocolOptions(catalog, 'claude')).toEqual([])
  })

  it('returns null for a persisted identity removed from the catalog', () => {
    const catalog = parseLlmCatalogResponse(rawCatalog())

    expect(
      findCredentialProfileForBinding(catalog, 'removed-provider', 'removed-protocol'),
    ).toBeNull()
  })

  it('builds a stable in-memory connection fingerprint', () => {
    const first = stableConnectionFingerprint({
      providerId: 'openai',
      protocolId: 'openai_responses',
      values: { OPENAI_MODEL: 'gpt-5', OPENAI_API_KEY: 'secret' },
    })
    const reordered = stableConnectionFingerprint({
      providerId: 'openai',
      protocolId: 'openai_responses',
      values: { OPENAI_API_KEY: 'secret', OPENAI_MODEL: 'gpt-5' },
    })

    expect(reordered).toBe(first)
    expect(
      stableConnectionFingerprint({
        providerId: 'deepseek',
        protocolId: 'chat_completions',
        values: { OPENAI_API_KEY: 'secret', OPENAI_MODEL: 'gpt-5' },
      }),
    ).not.toBe(first)
    expect(
      stableConnectionFingerprint({
        providerId: 'openai',
        protocolId: 'openai_responses',
        values: { OPENAI_API_KEY: 'changed', OPENAI_MODEL: 'gpt-5' },
      }),
    ).not.toBe(first)
  })
})

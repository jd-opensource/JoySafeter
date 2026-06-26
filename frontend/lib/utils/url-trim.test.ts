import { describe, expect, it } from 'vitest'

import { isConfigStringKey, isUrlLikeKey, trimConfigStringFields } from './url-trim'

describe('url trim utilities', () => {
  it('detects url-like keys across common naming styles', () => {
    expect(isUrlLikeKey('url')).toBe(true)
    expect(isUrlLikeKey('source_url')).toBe(true)
    expect(isUrlLikeKey('mcpServerUrl')).toBe(true)
    expect(isUrlLikeKey('OPENAI_BASE_URL')).toBe(true)
    expect(isUrlLikeKey('token_endpoint')).toBe(true)
    expect(isUrlLikeKey('authorization_token')).toBe(false)
    expect(isUrlLikeKey('OPENAI_API_KEY')).toBe(false)
    expect(isUrlLikeKey('curl')).toBe(false)
  })

  it('detects config string keys that should be trimmed', () => {
    expect(isConfigStringKey('OPENAI_API_KEY')).toBe(true)
    expect(isConfigStringKey('ANTHROPIC_AUTH_TOKEN')).toBe(true)
    expect(isConfigStringKey('authorization_token')).toBe(true)
    expect(isConfigStringKey('model')).toBe(true)
    expect(isConfigStringKey('description')).toBe(true)
    expect(isConfigStringKey('content')).toBe(false)
    expect(isConfigStringKey('system_prompt')).toBe(false)
  })

  it('recursively trims only config-like string fields', () => {
    const input = {
      name: ' keep spaces ',
      description: ' trim description ',
      content: ' keep content ',
      source_url: ' https://example.com/skill.git ',
      data: {
        OPENAI_BASE_URL: ' https://api.openai.com/v1 ',
        OPENAI_API_KEY: ' sk-test ',
        OPENAI_MODEL: ' gpt-5.3-codex ',
      },
      repos: [
        {
          url: ' https://github.com/acme/repo.git ',
          authorization_token: ' token ',
        },
      ],
    }

    expect(trimConfigStringFields(input)).toEqual({
      name: 'keep spaces',
      description: 'trim description',
      content: ' keep content ',
      source_url: 'https://example.com/skill.git',
      data: {
        OPENAI_BASE_URL: 'https://api.openai.com/v1',
        OPENAI_API_KEY: 'sk-test',
        OPENAI_MODEL: 'gpt-5.3-codex',
      },
      repos: [
        {
          url: 'https://github.com/acme/repo.git',
          authorization_token: 'token',
        },
      ],
    })
  })
})

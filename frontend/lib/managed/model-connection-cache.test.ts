import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import type { Credential } from '@/types/managed'

import { recordCreatedModelConnection } from './model-connection-cache'

const credential: Credential = {
  id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
  name: 'OpenAI authoring',
  kind: 'model',
  provider: 'openai',
  protocol: 'openai_responses',
  model: 'gpt-5.5',
  compatible_engine_ids: ['codex'],
  is_default: false,
  auth_scheme: null,
  archived_at: null,
  created_at: '2026-09-02T00:00:00Z',
  updated_at: '2026-09-02T00:00:00Z',
}

describe('recordCreatedModelConnection', () => {
  it('updates every loaded model-connection projection without duplicates', () => {
    const queryClient = new QueryClient()
    const scopeKey = 'org-a:project-a'
    queryClient.setQueryData(['compatible-credentials', scopeKey, 'codex', 'catalog-v1'], [])
    queryClient.setQueryData(['active-model-connections', scopeKey, 'catalog-v1'], [])
    queryClient.setQueryData(
      ['protocol-credentials', scopeKey, 'openai_responses', 'catalog-v1'],
      [credential],
    )

    recordCreatedModelConnection(queryClient, scopeKey, 'codex', credential)

    expect(
      queryClient.getQueryData(['compatible-credentials', scopeKey, 'codex', 'catalog-v1']),
    ).toEqual([credential])
    expect(queryClient.getQueryData(['active-model-connections', scopeKey, 'catalog-v1'])).toEqual([
      credential,
    ])
    expect(
      queryClient.getQueryData([
        'protocol-credentials',
        scopeKey,
        'openai_responses',
        'catalog-v1',
      ]),
    ).toEqual([credential])
  })

  it('updates a platform consumer projection', () => {
    const queryClient = new QueryClient()
    const scopeKey = 'org-a:project-a'
    queryClient.setQueryData(
      ['consumer-credentials', scopeKey, 'skill_ai_authoring', 'catalog-v1'],
      [],
    )

    recordCreatedModelConnection(
      queryClient,
      scopeKey,
      'skill_ai_authoring',
      credential,
      'consumer',
    )

    expect(
      queryClient.getQueryData([
        'consumer-credentials',
        scopeKey,
        'skill_ai_authoring',
        'catalog-v1',
      ]),
    ).toEqual([credential])
  })
})

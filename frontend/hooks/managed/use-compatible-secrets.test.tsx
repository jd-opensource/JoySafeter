import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'

import {
  compatibleSecretsQueryKey,
  useCompatibleSecrets,
  useProtocolSecrets,
  useLlmSecretByName,
} from './use-compatible-secrets'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  hasManagedRequestScope: () => true,
  managedRequestOptions: () => ({
    headers: { 'X-Org-Id': 'org-a', 'X-Project-Id': 'project-a' },
    skipManagedContext: true,
  }),
  useManagedRequestScope: () => ({
    orgId: 'org-a',
    projectId: 'project-a',
    key: 'org-a:project-a',
  }),
}))
vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({
    data: { version: 'catalog-v1' },
    isSuccess: true,
  }),
}))

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const UUID_A = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const UUID_B = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'

function secret(id: string, name: string, isDefault = false) {
  return {
    id: `secret_${id}`,
    name,
    kind: 'llm',
    provider: 'openai',
    protocol: 'openai_responses',
    model: 'gpt-5',
    compatible_engine_ids: ['codex', 'native', 'pi'],
    is_default: isDefault,
    keys: ['OPENAI_API_KEY'],
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useCompatibleSecrets', () => {
  afterEach(() => vi.clearAllMocks())

  it('requests the selected engine and follows all cursor pages', async () => {
    managedGetMock
      .mockResolvedValueOnce({
        data: [secret(UUID_A, 'openai-primary', true)],
        has_more: true,
        last_id: `secret_${UUID_A}`,
      })
      .mockResolvedValueOnce({
        data: [secret(UUID_B, 'openai-backup')],
        has_more: false,
        last_id: `secret_${UUID_B}`,
      })

    const { result } = renderHook(
      () => useCompatibleSecrets({ engineId: 'codex', enabled: true }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.map((item) => item.name)).toEqual([
      'openai-primary',
      'openai-backup',
    ])
    expect(managedGetMock.mock.calls[0][0]).toContain('kind=llm')
    expect(managedGetMock.mock.calls[0][0]).toContain('compatible_engine=codex')
    expect(managedGetMock.mock.calls[1][0]).toContain(`after_id=secret_${UUID_A}`)
  })

  it('includes the catalog version in the derived compatibility query key', () => {
    expect(compatibleSecretsQueryKey('org-a:project-a', 'codex', 'catalog-v2')).toEqual([
      'compatible-secrets',
      'org-a:project-a',
      'codex',
      'catalog-v2',
    ])
  })

  it('does not request without an engine', () => {
    const { result } = renderHook(() => useCompatibleSecrets({ engineId: '', enabled: true }), {
      wrapper,
    })

    expect(result.current.fetchStatus).toBe('idle')
    expect(managedGetMock).not.toHaveBeenCalled()
  })

  it('loads exact LLM Secret metadata by name for edit conflicts', async () => {
    managedGetMock.mockResolvedValueOnce({
      data: [secret(UUID_A, 'persisted-secret')],
      has_more: false,
      last_id: `secret_${UUID_A}`,
    })

    const { result } = renderHook(
      () => useLlmSecretByName({ name: 'persisted-secret', enabled: true }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.name).toBe('persisted-secret')
    expect(managedGetMock.mock.calls[0][0]).toContain('kind=llm')
    expect(managedGetMock.mock.calls[0][0]).toContain('name=persisted-secret')
  })

  it('loads all LLM secrets for an explicit protocol consumer', async () => {
    managedGetMock.mockResolvedValueOnce({
      data: [secret(UUID_A, 'authoring-openai')],
      has_more: false,
      last_id: `secret_${UUID_A}`,
    })

    const { result } = renderHook(
      () => useProtocolSecrets({ protocolId: 'openai_responses', enabled: true }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(managedGetMock.mock.calls[0][0]).toContain('kind=llm')
    expect(managedGetMock.mock.calls[0][0]).toContain('protocol=openai_responses')
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'

import {
  fetchAllServiceCredentials,
  serviceCredentialsQueryKey,
  useServiceCredentials,
} from './use-service-credentials'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))
const requestScopeState = vi.hoisted(() => ({
  scope: {
    orgId: 'org-a',
    projectId: 'project-a',
    key: 'org-a:project-a',
  } as ManagedRequestScope,
}))
vi.mock('@/lib/managed/request-scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/managed/request-scope')>()
  return {
    ...actual,
    useManagedRequestScope: () => requestScopeState.scope,
  }
})

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const SECRET_ID_A = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const SECRET_ID_B = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'
const scope: ManagedRequestScope = {
  orgId: 'org-a',
  projectId: 'project-a',
  key: 'org-a:project-a',
}

function genericSecret(name: string, id: string, data: Record<string, string>) {
  return {
    id,
    name,
    kind: 'service',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    data,
    archived_at: null,
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useServiceCredentials', () => {
  afterEach(() => {
    requestScopeState.scope = scope
    vi.clearAllMocks()
  })

  it('loads every Service Credential page and preserves resource IDs and fields', async () => {
    managedGetMock
      .mockResolvedValueOnce({
        data: [genericSecret('service-a', SECRET_ID_A, { TOKEN: 'v' })],
        has_more: true,
        last_id: SECRET_ID_A,
      })
      .mockResolvedValueOnce({
        data: [genericSecret('service-b', SECRET_ID_B, { API_KEY: 'v' })],
        has_more: false,
        last_id: SECRET_ID_B,
      })

    const { result } = renderHook(() => useServiceCredentials(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(managedGetMock.mock.calls[0][0]).toBe('/credentials?limit=100&kind=service')
    expect(managedGetMock.mock.calls[1][0]).toBe(
      `/credentials?limit=100&kind=service&after_id=${SECRET_ID_A}`,
    )
    expect(result.current.data).toEqual([
      expect.objectContaining({ id: SECRET_ID_A, name: 'service-a', data: { TOKEN: 'v' } }),
      expect.objectContaining({ id: SECRET_ID_B, name: 'service-b', data: { API_KEY: 'v' } }),
    ])
    expect(serviceCredentialsQueryKey('org-a:project-a')).toEqual([
      'service-credentials',
      'org-a:project-a',
    ])
  })

  it('excludes blank and noncanonical historical names from selector query results', async () => {
    managedGetMock.mockResolvedValueOnce({
      data: [
        genericSecret('', SECRET_ID_A, { TOKEN: 'v' }),
        genericSecret(' padded-service ', SECRET_ID_A, { TOKEN: 'v' }),
        genericSecret('canonical-service', SECRET_ID_B, { API_KEY: 'v' }),
      ],
      has_more: false,
      last_id: SECRET_ID_B,
    })

    await expect(fetchAllServiceCredentials(scope)).resolves.toEqual([
      expect.objectContaining({ name: 'canonical-service' }),
    ])
  })

  it('rejects a repeated pagination cursor instead of looping', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: true, last_id: SECRET_ID_A })

    await expect(fetchAllServiceCredentials(scope)).rejects.toThrow(
      'Service Credential pagination returned an invalid cursor',
    )
    expect(managedGetMock).toHaveBeenCalledTimes(2)
  })

  it('rejects a multi-page cursor cycle before requesting a duplicate page', async () => {
    managedGetMock
      .mockResolvedValueOnce({ data: [], has_more: true, last_id: SECRET_ID_A })
      .mockResolvedValueOnce({ data: [], has_more: true, last_id: SECRET_ID_B })
      .mockResolvedValueOnce({ data: [], has_more: true, last_id: SECRET_ID_A })
      .mockResolvedValue({ data: [], has_more: true, last_id: SECRET_ID_A })

    await expect(fetchAllServiceCredentials(scope)).rejects.toThrow(
      'Service Credential pagination returned an invalid cursor',
    )
    expect(managedGetMock).toHaveBeenCalledTimes(3)
  })

  it.each([
    ['organization', { orgId: null, projectId: 'project-a', key: ':project-a' }],
    ['project', { orgId: 'org-a', projectId: null, key: 'org-a:' }],
  ] as const)('does not request with a missing %s scope', (_label, missingScope) => {
    requestScopeState.scope = missingScope

    const { result } = renderHook(() => useServiceCredentials(), { wrapper })

    expect(result.current.fetchStatus).toBe('idle')
    expect(managedGetMock).not.toHaveBeenCalled()
  })

  it('does not request when explicitly disabled', () => {
    const { result } = renderHook(() => useServiceCredentials({ enabled: false }), { wrapper })

    expect(result.current.fetchStatus).toBe('idle')
    expect(managedGetMock).not.toHaveBeenCalled()
  })
})

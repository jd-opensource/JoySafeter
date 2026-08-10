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

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const SECRET_ID_A = 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const SECRET_ID_B = 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'
const scope: ManagedRequestScope = {
  orgId: 'org-a',
  projectId: 'project-a',
  key: 'org-a:project-a',
}

function genericSecret(name: string, id: string, keys: string[]) {
  return {
    id,
    name,
    kind: 'generic',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    keys,
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useServiceCredentials', () => {
  afterEach(() => vi.clearAllMocks())

  it('loads every Generic Secret page and preserves resource IDs and keys', async () => {
    managedGetMock
      .mockResolvedValueOnce({
        data: [genericSecret('service-a', SECRET_ID_A, ['TOKEN'])],
        has_more: true,
        last_id: SECRET_ID_A,
      })
      .mockResolvedValueOnce({
        data: [genericSecret('service-b', SECRET_ID_B, ['API_KEY'])],
        has_more: false,
        last_id: SECRET_ID_B,
      })

    const { result } = renderHook(() => useServiceCredentials(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(managedGetMock.mock.calls[0][0]).toBe('/secrets?limit=100&kind=generic')
    expect(managedGetMock.mock.calls[1][0]).toBe(
      `/secrets?limit=100&kind=generic&after_id=${SECRET_ID_A}`,
    )
    expect(result.current.data).toEqual([
      expect.objectContaining({ id: SECRET_ID_A, name: 'service-a', keys: ['TOKEN'] }),
      expect.objectContaining({ id: SECRET_ID_B, name: 'service-b', keys: ['API_KEY'] }),
    ])
    expect(serviceCredentialsQueryKey('org-a:project-a')).toEqual([
      'service-credentials',
      'org-a:project-a',
    ])
  })

  it('rejects a repeated pagination cursor instead of looping', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: true, last_id: SECRET_ID_A })

    await expect(fetchAllServiceCredentials(scope)).rejects.toThrow(
      'Service Credential pagination returned an invalid cursor',
    )
    expect(managedGetMock).toHaveBeenCalledTimes(2)
  })
})

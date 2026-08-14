import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn(), managedDelete: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({ useCurrentProjectReadOnly: () => false }))

import { managedGet } from '@/lib/api-client'

import { ServiceCredentialList } from './service-credential-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('ServiceCredentialList', () => {
  it('requests only kind=service and never touches the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(<Wrap><ServiceCredentialList onCreate={() => {}} /></Wrap>)
    await waitFor(() => {
      const cred = managedGetMock.mock.calls.find(([u]) => (u as string).startsWith('/credentials'))
      expect(cred![0]).toContain('kind=service')
    })
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(false)
  })
})

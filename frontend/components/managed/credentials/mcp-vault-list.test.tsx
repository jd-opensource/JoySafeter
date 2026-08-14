import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn(), managedPost: vi.fn(), managedDelete: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))

import { managedGet } from '@/lib/api-client'

import { McpVaultList } from './mcp-vault-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('McpVaultList', () => {
  it('lists credential-groups and never touches the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(<Wrap><McpVaultList onCreate={() => {}} /></Wrap>)
    await waitFor(() =>
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/credential-groups'))).toBe(true),
    )
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(false)
  })
})

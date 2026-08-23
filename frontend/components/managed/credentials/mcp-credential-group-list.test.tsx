import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const scopeMock = { orgId: 'o', projectId: 'p', key: 'o:p' }

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedDelete: vi.fn(),
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => scopeMock,
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => true,
}))
vi.mock('@/hooks/managed/use-scoped-actions', () => ({
  useScopedActions: () => ({
    scopeRef: { current: scopeMock.key },
    scope: scopeMock,
    readOnly: false,
    beginAction: () => ({ runId: 1, scope: scopeMock.key, requestScope: scopeMock }),
    isCurrentAction: () => true,
    scopeIsActive: () => true,
    bumpRun: () => {},
  }),
}))
vi.mock('@/components/managed/shared', () => ({
  ConfirmDialog: ({
    open,
    confirmLabel,
    onConfirm,
  }: {
    open: boolean
    confirmLabel: string
    onConfirm: () => void
  }) => (open ? <button onClick={onConfirm}>confirm:{confirmLabel}</button> : null),
  RelativeTime: () => null,
  ResourceErrorState: () => null,
  StatusBadge: () => null,
}))
vi.mock('./credential-list-panel', () => ({
  CredentialListPanel: ({
    data,
    actionMenu,
  }: {
    data: Array<{ id: string; name: string }>
    actionMenu: (row: { id: string; name: string }) => Array<{ label: string; onClick: () => void }>
  }) => (
    <div>
      {data.map((row) => (
        <div key={row.id} data-testid={row.id}>
          {actionMenu(row).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
}))

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'

import { McpCredentialGroupList } from './mcp-credential-group-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const GROUP = 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('McpCredentialGroupList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists credential-groups and never touches the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(
      <Wrap>
        <McpCredentialGroupList onCreate={() => {}} />
      </Wrap>,
    )
    await waitFor(() =>
      expect(
        managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/credential-groups')),
      ).toBe(true),
    )
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(
      false,
    )
  })

  it('restores and deletes an archived credential group', async () => {
    managedGetMock.mockResolvedValue({
      data: [
        {
          id: GROUP,
          name: 'Archived group',
          archived_at: '2026-08-14T00:00:00Z',
          created_at: '2026-08-13T00:00:00Z',
          updated_at: '2026-08-14T00:00:00Z',
        },
      ],
      has_more: false,
    })
    const state = { searchQuery: '', createdFilter: 'all', showArchived: true, pageSize: 10 }
    render(
      <Wrap>
        <McpCredentialGroupList onCreate={() => {}} state={state} />
      </Wrap>,
    )

    const row = await screen.findByTestId(GROUP)
    fireEvent.click(within(row).getByRole('button', { name: 'common.restore' }))
    fireEvent.click(screen.getByRole('button', { name: 'confirm:common.restore' }))
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credential-groups/${GROUP}/restore`,
        {},
        expect.anything(),
      ),
    )

    fireEvent.click(within(row).getByRole('button', { name: 'common.delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'confirm:common.delete' }))
    await waitFor(() =>
      expect(managedDeleteMock).toHaveBeenCalledWith(
        `/credential-groups/${GROUP}`,
        expect.anything(),
      ),
    )
  })
})

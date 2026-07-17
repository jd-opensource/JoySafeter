import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { managedDelete, managedGet, managedPost } from '@/lib/api-client'

import { SkillCollaboratorsPanel } from './skill-collaborators-panel'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedDelete: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

const scope = { orgId: 'org1', projectId: 'proj1', key: 'org1:proj1' }

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const collaborators = [
  { user_id: 'u-1', email: 'ada@example.com', display_name: 'Ada', role: 'editor' },
  { user_id: 'u-2', email: 'bob@example.com', display_name: 'Bob', role: 'viewer' },
]

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(managedGet).mockImplementation((path: string) =>
    path.includes('collaborators')
      ? Promise.resolve(collaborators as unknown as never)
      : Promise.resolve([] as unknown as never),
  )
})

afterEach(cleanup)

describe('SkillCollaboratorsPanel', () => {
  it('lists collaborators when the caller can manage', async () => {
    const { getByText } = wrap(
      <SkillCollaboratorsPanel
        skillId="abc"
        capability="owner"
        requestScope={scope}
        queryScopeKey={scope.key}
      />,
    )
    await waitFor(() => expect(getByText('ada@example.com')).toBeTruthy())
    expect(getByText('bob@example.com')).toBeTruthy()
    expect(vi.mocked(managedGet)).toHaveBeenCalledWith(
      '/skills/abc/collaborators',
      expect.anything(),
    )
  })

  it('does not fetch or render management UI for a non-admin capability', async () => {
    const { getByText, queryByText } = wrap(
      <SkillCollaboratorsPanel
        skillId="abc"
        capability="editor"
        requestScope={scope}
        queryScopeKey={scope.key}
      />,
    )
    expect(getByText('managed.skills.collaborators.adminOnly')).toBeTruthy()
    expect(queryByText('ada@example.com')).toBeNull()
    expect(vi.mocked(managedGet)).not.toHaveBeenCalled()
  })

  it('revokes a collaborator through the confirm dialog', async () => {
    vi.mocked(managedDelete).mockResolvedValue(undefined as unknown as never)
    const { getAllByText, getByText } = wrap(
      <SkillCollaboratorsPanel
        skillId="abc"
        capability="admin"
        requestScope={scope}
        queryScopeKey={scope.key}
      />,
    )
    await waitFor(() => expect(getByText('ada@example.com')).toBeTruthy())

    // First "remove" element is the row action button; clicking opens the dialog.
    fireEvent.click(getAllByText('managed.skills.collaborators.remove')[0])
    fireEvent.click(getByText('common.delete'))

    await waitFor(() =>
      expect(vi.mocked(managedDelete)).toHaveBeenCalledWith(
        '/skills/abc/collaborators/u-1',
        expect.anything(),
      ),
    )
    expect(vi.mocked(managedPost)).not.toHaveBeenCalled()
  })
})

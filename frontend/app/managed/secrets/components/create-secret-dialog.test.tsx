import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { managedPost } from '@/lib/api-client'

import { CreateSecretDialog } from './create-secret-dialog'

vi.mock('@/lib/api-client', () => ({ managedPost: vi.fn() }))
vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/managed/request-scope', () => ({
  managedRequestOptions: () => ({}),
  useManagedRequestScope: () => ({ orgId: 'org-a', projectId: 'project-a', key: 'scope' }),
}))
vi.mock('@/components/managed/llm/llm-secret-configurator', () => ({
  LlmSecretConfigurator: () => <div data-testid="llm-configurator">llm</div>,
}))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: any) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <h2>{children}</h2>,
  DialogDescription: ({ children }: any) => <p>{children}</p>,
}))

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

describe('CreateSecretDialog', () => {
  it('defaults to inline LLM configuration', () => {
    render(<CreateSecretDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />)

    expect(screen.getByTestId('llm-configurator')).toBeTruthy()
  })

  it('creates an explicit service credential without provider or protocol', async () => {
    managedPostMock.mockResolvedValueOnce({
      id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
      name: 'github-token',
      kind: 'service',
      provider: null,
      protocol: null,
      model: null,
      compatible_engine_ids: [],
      is_default: false,
      data: { GITHUB_TOKEN: '********' },
      created_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    })
    render(<CreateSecretDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />)

    fireEvent.click(screen.getByRole('tab', { name: 'managed.llm.genericSecret' }))
    fireEvent.change(screen.getByLabelText('managed.llm.configurationName'), {
      target: { value: 'github-token' },
    })
    fireEvent.change(screen.getByLabelText('managed.llm.genericKey'), {
      target: { value: 'GITHUB_TOKEN' },
    })
    fireEvent.change(screen.getByLabelText('managed.llm.genericValue'), {
      target: { value: 'ghp-secret' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'common.create' }))

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][0]).toBe('/credentials')
    expect(managedPostMock.mock.calls[0][1]).toEqual({
      kind: 'service',
      name: 'github-token',
      data: { GITHUB_TOKEN: 'ghp-secret' },
      is_default: false,
    })
  })
})

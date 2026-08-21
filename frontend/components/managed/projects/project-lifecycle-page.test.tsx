import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/managed/errors', () => ({ toastOperationError: vi.fn() }))

vi.mock('@/providers/permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('ProjectLifecyclePage', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('requires the exact project name before archive confirmation', async () => {
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'project-a',
      name: 'Critical Project',
      slug: 'critical-project',
      is_default: false,
      triggers_paused: false,
      archived_at: null,
      capability: 'admin',
    })
    const { ProjectLifecyclePage } = await import('./project-lifecycle-page')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProjectLifecyclePage projectId="project-a" />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(view.getByText('Critical Project')).toBeTruthy())
    fireEvent.click(view.getByText('managed.projectSettings.lifecycle.archiveAction'))

    const confirmation = view.getByPlaceholderText(
      'managed.projectSettings.lifecycle.archiveNamePlaceholder',
    )
    const confirmButton = view.getByText(
      'managed.projectSettings.lifecycle.confirmArchive',
    ) as HTMLButtonElement
    expect(confirmButton.disabled).toBe(true)

    fireEvent.change(confirmation, { target: { value: 'Wrong Project' } })
    expect(confirmButton.disabled).toBe(true)

    fireEvent.change(confirmation, { target: { value: 'Critical Project' } })
    expect(confirmButton.disabled).toBe(false)
  })
})

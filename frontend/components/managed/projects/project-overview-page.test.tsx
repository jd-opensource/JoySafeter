import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedGet, managedPatch } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID } from '@/test-utils/entity-ids'

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/managed/errors', () => ({ toastOperationError: vi.fn() }))

vi.mock('@/providers/permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: false }),
}))

vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: { setState: vi.fn() },
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('ProjectOverviewPage', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('lets a project admin rename without granting organization-only slug control', async () => {
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: PROJECT_ID,
      org_id: ORGANIZATION_ID,
      name: 'Project A',
      slug: 'project-a',
      is_default: true,
      archived_at: null,
      capability: 'admin',
    })
    ;(managedPatch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: PROJECT_ID,
      org_id: ORGANIZATION_ID,
      name: 'Renamed Project',
      slug: 'project-a',
      is_default: true,
      archived_at: null,
      capability: 'admin',
    })

    const { ProjectOverviewPage } = await import('./project-overview-page')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProjectOverviewPage projectId={PROJECT_ID} />
      </QueryClientProvider>,
    )

    await view.findByText('manage.projects.projectName')
    const [nameInput, slugInput] = view.getAllByRole('textbox') as HTMLInputElement[]
    expect((nameInput as HTMLInputElement).disabled).toBe(false)
    expect(slugInput.disabled).toBe(true)

    fireEvent.change(nameInput, { target: { value: 'Renamed Project' } })
    fireEvent.click(view.getByText('common.save'))

    await waitFor(() =>
      expect(managedPatch).toHaveBeenCalledWith(`/auth/projects/${PROJECT_ID}`, {
        name: 'Renamed Project',
      }),
    )
  })
})

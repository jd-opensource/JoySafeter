import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managedPost } from '@/lib/api-client'
import { toastSuccess } from '@/lib/utils/toast'
import { useProjectStore } from '@/stores/managed/project-store'

vi.mock('@/lib/api-client', () => ({
  managedPost: vi.fn(),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) =>
      params ? `${key}:${JSON.stringify(params)}` : key,
  }),
}))

vi.mock('@/lib/utils/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}))

vi.mock('@/components/ui/button', () => ({
  buttonVariants: () => '',
  Button: ({
    children,
    disabled,
    onClick,
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
  }) => (
    <button type="button" disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>')
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const toastSuccessMock = toastSuccess as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function renderWithClient(ui: ReactNode, queryClient: QueryClient) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('SkillLifecycleActions lifecycle', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      currentProject: null,
      organizations: [],
      projects: [],
    })
  })

  it('does not toast or invalidate queries after a lifecycle mutation resolves post-unmount', async () => {
    const { SkillLifecycleActions } = await import('./skill-lifecycle-actions')
    const transitionResponse = deferred<{
      skill_id: string
      from_status: string
      to_status: string
    }>()
    managedPostMock.mockReturnValueOnce(transitionResponse.promise)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: true,
        archived_at: null,
        // Lifecycle transitions require ADMIN capability (backend gate).
        capability: 'admin',
      },
      organizations: [],
      projects: [],
    })

    const view = renderWithClient(
      <SkillLifecycleActions
        skillId="skill_123"
        currentStatus="draft"
        requestScope={{ orgId: 'org-a', projectId: 'project-a', key: 'org-a:project-a' }}
        operationScope="org-a:project-a:skill_123"
        invalidateKeys={[['skills', 'org-a:project-a']]}
      />,
      queryClient,
    )

    await act(async () => {
      fireEvent.click(view.getByText('managed.skills.transition.submitForReview'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/skills/123/submit-review',
      {},
      {
        headers: {
          'X-Org-Id': 'org-a',
          'X-Project-Id': 'project-a',
        },
        skipManagedContext: true,
      },
    )

    view.unmount()

    await act(async () => {
      transitionResponse.resolve({
        skill_id: 'skill_123',
        from_status: 'draft',
        to_status: 'pending_review',
      })
      await transitionResponse.promise
      await Promise.resolve()
    })

    expect(toastSuccessMock).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
}))

import { managedGet } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import { SESSION_ID } from '@/test-utils/entity-ids'

import { usePaginatedList } from './use-paginated-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

interface Item {
  id: string
  name: string
}

function Harness() {
  const { data } = usePaginatedList<Item>({
    queryKey: 'items',
    path: '/items',
  })

  return <div data-testid="items">{data.map((item) => item.name).join(',')}</div>
}

function HarnessWithNext() {
  const { data, goNext, goToPage, hasNext, page } = usePaginatedList<Item>({
    queryKey: 'items',
    path: '/items',
  })

  return (
    <div>
      <div data-testid="items">{data.map((item) => item.name).join(',')}</div>
      <div data-testid="page">{page}</div>
      <button data-testid="next" disabled={!hasNext} onClick={goNext}>
        next
      </button>
      <button data-testid="page-2" onClick={() => goToPage(2)}>
        page 2
      </button>
    </div>
  )
}

function HarnessWithQueryPath() {
  const { data, goNext, hasNext } = usePaginatedList<Item>({
    queryKey: 'files',
    path: `/files?scope_id=${SESSION_ID}`,
  })

  return (
    <div>
      <div data-testid="items">{data.map((item) => item.name).join(',')}</div>
      <button data-testid="next" disabled={!hasNext} onClick={goNext}>
        next
      </button>
    </div>
  )
}

function HarnessWithParser() {
  const { data } = usePaginatedList<Item>({
    queryKey: 'parsed-items',
    path: '/parsed-items',
    parseItem: (item) => {
      const raw = item as Item
      return { ...raw, name: raw.name.toUpperCase() }
    },
  })

  return <div data-testid="items">{data.map((item) => item.name).join(',')}</div>
}

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  const view = render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)

  return { ...view, queryClient }
}

describe('usePaginatedList managed context isolation', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null })
    window.sessionStorage.clear()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null })
    window.sessionStorage.clear()
  })

  it('does not request managed lists until org and project context are available', async () => {
    const { getByTestId } = renderWithQueryClient(<Harness />)

    await act(async () => {
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('')
    expect(managedGetMock).not.toHaveBeenCalled()
  })

  it('binds list requests to the same managed scope as the query key', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    managedGetMock.mockResolvedValue({ data: [], has_more: false })

    renderWithQueryClient(<Harness />)

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/items?limit=10', {
        headers: {
          'X-Org-Id': 'org-a',
          'X-Project-Id': 'project-a',
        },
        skipManagedContext: true,
      })
    })
  })

  it('parses list items before exposing or caching them', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    managedGetMock.mockResolvedValue({
      data: [{ id: 'item-a', name: 'raw item' }],
      has_more: false,
    })

    const { getByTestId } = renderWithQueryClient(<HarnessWithParser />)

    await waitFor(() => expect(getByTestId('items').textContent).toBe('RAW ITEM'))
  })

  it('does not reuse a previous project page after managed project changes', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    managedGetMock.mockImplementation(async () => {
      const projectId = useProjectStore.getState().currentProjectId
      return {
        data: [
          {
            id: projectId === 'project-b' ? 'item-b' : 'item-a',
            name: projectId === 'project-b' ? 'Project B item' : 'Project A item',
          },
        ],
        has_more: false,
      }
    })

    const { getByTestId, queryClient, rerender } = renderWithQueryClient(<Harness />)

    await act(async () => {
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Project A item')
    expect(managedGetMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <Harness />
        </QueryClientProvider>,
      )
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Project B item')
    expect(managedGetMock).toHaveBeenCalledTimes(2)
  })

  it('does not expose the previous project data while the next project page is loading', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const projectBPage = deferred<{
      data: Array<{ id: string; name: string }>
      has_more: boolean
    }>()
    managedGetMock.mockImplementation(async () => {
      const projectId = useProjectStore.getState().currentProjectId
      if (projectId === 'project-b') {
        return projectBPage.promise
      }
      return {
        data: [{ id: 'item-a', name: 'Project A item' }],
        has_more: false,
      }
    })

    const { getByTestId, queryClient, rerender } = renderWithQueryClient(<Harness />)

    await act(async () => {
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Project A item')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <Harness />
        </QueryClientProvider>,
      )
      await wait(0)
    })

    expect(getByTestId('items').textContent).toBe('')

    await act(async () => {
      projectBPage.resolve({
        data: [{ id: 'item-b', name: 'Project B item' }],
        has_more: false,
      })
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Project B item')
  })

  it('drops the previous project cursor before fetching the next project page', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const requestedPaths: string[] = []
    managedGetMock.mockImplementation(async (path: string) => {
      requestedPaths.push(path)
      const projectId = useProjectStore.getState().currentProjectId
      if (projectId === 'project-b') {
        return {
          data: [{ id: 'item-b-1', name: 'Project B first page' }],
          has_more: false,
          last_id: 'item-b-1',
        }
      }
      if (path.includes('after_id=item-a-1')) {
        return {
          data: [{ id: 'item-a-2', name: 'Project A second page' }],
          has_more: false,
          last_id: 'item-a-2',
        }
      }
      return {
        data: [{ id: 'item-a-1', name: 'Project A first page' }],
        has_more: true,
        last_id: 'item-a-1',
      }
    })

    const { getByTestId, queryClient, rerender } = renderWithQueryClient(<HarnessWithNext />)

    await act(async () => {
      await wait(20)
    })

    await act(async () => {
      getByTestId('next').click()
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Project A second page')
    expect(requestedPaths.some((path) => path.includes('after_id=item-a-1'))).toBe(true)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <HarnessWithNext />
        </QueryClientProvider>,
      )
      await wait(20)
    })

    const lastPath = requestedPaths[requestedPaths.length - 1]
    expect(lastPath).not.toContain('after_id=item-a-1')
    expect(getByTestId('items').textContent).toBe('Project B first page')
    expect(getByTestId('page').textContent).toBe('1')
  })

  it('normalizes prefixed page cursors and preserves existing path query params', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const requestedPaths: string[] = []
    managedGetMock.mockImplementation(async (path: string) => {
      requestedPaths.push(path)
      if (path.includes('after_id=file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f015')) {
        return {
          data: [
            { id: 'file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f016', name: 'Second file' },
          ],
          has_more: false,
          last_id: 'file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f016',
        }
      }
      return {
        data: [{ id: 'file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f015', name: 'First file' }],
        has_more: true,
        last_id: 'file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f015',
      }
    })

    const { getByTestId } = renderWithQueryClient(<HarnessWithQueryPath />)

    await act(async () => {
      await wait(20)
    })

    expect(requestedPaths[0]).toBe(`/files?scope_id=${SESSION_ID}&limit=10`)

    await act(async () => {
      getByTestId('next').click()
      await wait(20)
    })

    expect(
      requestedPaths.some(
        (path) =>
          path ===
          `/files?scope_id=${SESSION_ID}&limit=10&after_id=file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f015`,
      ),
    ).toBe(true)
    expect(getByTestId('items').textContent).toBe('Second file')
  })

  it('uses the target page cursor when jumping backward by page number', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const requestedPaths: string[] = []
    managedGetMock.mockImplementation(async (path: string) => {
      requestedPaths.push(path)
      if (path.includes('after_id=item-2')) {
        return {
          data: [{ id: 'item-3', name: 'Third page' }],
          has_more: false,
          last_id: 'item-3',
        }
      }
      if (path.includes('after_id=item-1')) {
        return {
          data: [{ id: 'item-2', name: 'Second page' }],
          has_more: true,
          last_id: 'item-2',
        }
      }
      return {
        data: [{ id: 'item-1', name: 'First page' }],
        has_more: true,
        last_id: 'item-1',
      }
    })

    const { getByTestId } = renderWithQueryClient(<HarnessWithNext />)

    await act(async () => {
      await wait(20)
    })

    await act(async () => {
      getByTestId('next').click()
      await wait(20)
    })

    await act(async () => {
      getByTestId('next').click()
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Third page')
    expect(getByTestId('page').textContent).toBe('3')

    await act(async () => {
      getByTestId('page-2').click()
      await wait(20)
    })

    await waitFor(() => {
      expect(getByTestId('items').textContent).toBe('Second page')
      expect(getByTestId('page').textContent).toBe('2')
    })
    expect(requestedPaths.some((path) => path.includes('after_id=item-1'))).toBe(true)
  })

  it('keeps the current page visible while fetching another cursor in the same list scope', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const secondPage = deferred<{
      data: Array<{ id: string; name: string }>
      has_more: boolean
      last_id?: string
    }>()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.includes('after_id=item-1')) {
        return secondPage.promise
      }
      return {
        data: [{ id: 'item-1', name: 'First page' }],
        has_more: true,
        last_id: 'item-1',
      }
    })

    const { getByTestId } = renderWithQueryClient(<HarnessWithNext />)

    await act(async () => {
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('First page')

    await act(async () => {
      getByTestId('next').click()
      await wait(0)
    })

    expect(getByTestId('items').textContent).toBe('First page')
    expect(getByTestId('page').textContent).toBe('2')

    await act(async () => {
      secondPage.resolve({
        data: [{ id: 'item-2', name: 'Second page' }],
        has_more: false,
        last_id: 'item-2',
      })
      await wait(20)
    })

    expect(getByTestId('items').textContent).toBe('Second page')
  })

  it('restores the current page after returning to the same list scope', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.includes('after_id=item-1')) {
        return {
          data: [{ id: 'item-2', name: 'Second page' }],
          has_more: false,
          last_id: 'item-2',
        }
      }
      return {
        data: [{ id: 'item-1', name: 'First page' }],
        has_more: true,
        last_id: 'item-1',
      }
    })

    const firstView = renderWithQueryClient(<HarnessWithNext />)

    await act(async () => {
      await wait(20)
    })

    await act(async () => {
      firstView.getByTestId('next').click()
      await wait(20)
    })

    expect(firstView.getByTestId('page').textContent).toBe('2')
    expect(firstView.getByTestId('items').textContent).toBe('Second page')

    firstView.unmount()

    const secondView = renderWithQueryClient(<HarnessWithNext />)

    await waitFor(() => {
      expect(secondView.getByTestId('page').textContent).toBe('2')
      expect(secondView.getByTestId('items').textContent).toBe('Second page')
    })
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/providers/permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/lib/managed/filters', () => ({
  createCreatedTimeFilter: () => ({ id: 'created', label: 'created', options: [] }),
  filterByCreatedTime: () => true,
  matchesSearch: () => true,
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: ProjectRecord) => { label: string; onClick: () => void }[]
    data: ProjectRecord[]
  }) => (
    <div>
      {data.map((project) => (
        <div key={project.id}>
          <span>{project.name}</span>
          {actionMenu?.(project).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {project.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ title, action }: { title: string; action?: ReactNode }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))

vi.mock('@/components/ui/button', () => ({
  buttonVariants: () => '',
  Button: ({
    children,
    disabled,
    onClick,
    type = 'button',
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    onOpenChange,
    open,
  }: {
    children: ReactNode
    onOpenChange?: (open: boolean) => void
    open: boolean
  }) =>
    open ? (
      <div>
        {children}
        <button onClick={() => onOpenChange?.(false)}>dialog-close</button>
      </div>
    ) : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import ProjectsPage from './page'

interface ProjectRecord {
  id: string
  org_id: string
  name: string
  slug: string
  is_default: boolean
  archived_at?: string | null
  created_at?: string
}

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPatchMock = managedPatch as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function project(id: string, name: string): ProjectRecord {
  return {
    id,
    org_id: 'org-a',
    name,
    slug: name.toLowerCase(),
    is_default: false,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('ProjectsPage object lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedDeleteMock.mockReset()
    managedPatchMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedPatchMock.mockResolvedValue({})
    managedPostMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('does not reuse a project list cached under another organization', () => {
    const projectA = project('project-a', 'Alpha')
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['projects-list', false], [projectA])
    managedGetMock.mockReturnValue(new Promise(() => {}))
    useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })

    const { queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    expect(queryByText('Alpha')).toBeNull()
  })

  it('does not close the current create dialog when an older organization create finishes', async () => {
    const create = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    managedGetMock.mockResolvedValue([])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByDisplayValue, getByPlaceholderText, queryByDisplayValue, rerender } =
      render(
        <QueryClientProvider client={queryClient}>
          <ProjectsPage />
        </QueryClientProvider>,
      )

    await waitFor(() => {
      expect(getAllByText('manage.projects.create')[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.projects.namePlaceholder'), {
        target: { value: 'Alpha' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create').at(-1)!)
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/auth/projects', {
      name: 'Alpha',
      slug: 'alpha',
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <ProjectsPage />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.projects.namePlaceholder'), {
        target: { value: 'Beta' },
      })
    })

    expect(getByDisplayValue('Beta')).toBeTruthy()
    expect((getAllByText('manage.projects.create').at(-1)! as HTMLButtonElement).disabled).toBe(
      false,
    )

    await act(async () => {
      create.resolve({})
      await create.promise
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryByDisplayValue('Beta')).toBeTruthy()
    })
  })

  it('does not close a reopened create project dialog when an older create finishes', async () => {
    const create = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    managedGetMock.mockResolvedValue([])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByDisplayValue, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByText('manage.projects.create')[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.projects.namePlaceholder'), {
        target: { value: 'Alpha' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create').at(-1)!)
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.projects.namePlaceholder'), {
        target: { value: 'Beta' },
      })
    })

    await act(async () => {
      create.resolve({})
      await Promise.resolve()
    })

    expect(getByDisplayValue('Beta')).toBeTruthy()
  })

  it('does not create a project from an old organization dialog after the organization changes in the same tick', async () => {
    managedGetMock.mockResolvedValue([])
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByPlaceholderText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getAllByText('manage.projects.create')[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.projects.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.projects.namePlaceholder'), {
        target: { value: 'Project A Operations' },
      })
    })

    const oldCreateButton = getAllByText('manage.projects.create').at(-1)!

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(oldCreateButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/auth/projects', {
      name: 'Project A Operations',
      slug: 'project-a-operations',
    })
  })

  it('does not submit an edit target that is no longer in the current projects list', async () => {
    const projectA = project('project-a', 'Alpha')
    const projectB = project('project-b', 'Beta')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByDisplayValue, getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('project-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByDisplayValue('Alpha'), {
        target: { value: 'Alpha Edited' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(['projects-list', 'org-a', false], [projectB])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Beta')).toBeTruthy()
    })

    const saveButton = queryByText('common.save')
    if (saveButton) {
      await act(async () => {
        fireEvent.click(saveButton)
      })
    }

    expect(managedPatchMock).not.toHaveBeenCalled()
  })

  it('does not submit an edit target that leaves the current projects list during save', async () => {
    const projectA = project('project-a', 'Alpha')
    const projectB = project('project-b', 'Beta')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByDisplayValue, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('project-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByDisplayValue('Alpha'), {
        target: { value: 'Alpha Edited' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(['projects-list', 'org-a', false], [projectB])
      fireEvent.click(getByText('common.save'))
      await Promise.resolve()
    })

    expect(managedPatchMock).not.toHaveBeenCalledWith('/auth/projects/project-a', {
      name: 'Alpha Edited',
    })
  })

  it('does not archive a project target that leaves the current projects list during confirmation', async () => {
    const projectA = project('project-a', 'Alpha')
    const projectB = project('project-b', 'Beta')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('project-a:common.archive'))
    })

    await act(async () => {
      queryClient.setQueryData(['projects-list', 'org-a', false], [projectB])
      fireEvent.click(getByText('manage.projects.archive'))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/auth/projects/project-a')
  })

  it('does not archive an old organization project after the organization changes in the same tick', async () => {
    const projectA = project('project-a', 'Alpha')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('project-a:common.archive'))
    })

    const oldArchiveButton = getByText('manage.projects.archive')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(oldArchiveButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/auth/projects/project-a')
  })

  it('does not set default on a project target that leaves the current projects list', async () => {
    const projectA = project('project-a', 'Alpha')
    const projectB = project('project-b', 'Beta')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['projects-list', 'org-a', false], [projectB])
      fireEvent.click(getByText('project-a:manage.projects.setDefault'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/auth/projects/project-a/set-default', {})
  })

  it('does not submit a delete target that is no longer in the current projects list', async () => {
    const projectA = project('project-a', 'Alpha')
    const projectB = project('project-b', 'Beta')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('project-a:common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['projects-list', 'org-a', false], [projectB])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Beta')).toBeTruthy()
    })

    const deleteButton = queryByText('common.delete')
    if (deleteButton) {
      await act(async () => {
        fireEvent.click(deleteButton)
      })
    }

    expect(managedDeleteMock).not.toHaveBeenCalled()
  })

  it('does not submit a delete target that leaves the current projects list during confirmation', async () => {
    const projectA = project('project-a', 'Alpha')
    const projectB = project('project-b', 'Beta')
    managedGetMock.mockResolvedValue([projectA])

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Alpha')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('project-a:common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['projects-list', 'org-a', false], [projectB])
      fireEvent.click(getByText('common.delete'))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/auth/projects/project-a')
  })

  it('does not invalidate project lists from a create completion after the page unmounts', async () => {
    const create = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    managedGetMock.mockResolvedValue([])
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProjectsPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(view.getAllByText('manage.projects.create')[0]).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getAllByText('manage.projects.create')[0])
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('manage.projects.namePlaceholder'), {
        target: { value: 'Unmounted Project' },
      })
    })

    await act(async () => {
      fireEvent.click(view.getAllByText('manage.projects.create').at(-1)!)
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/auth/projects', {
      name: 'Unmounted Project',
      slug: 'unmounted-project',
    })

    view.unmount()

    await act(async () => {
      create.resolve({})
      await create.promise
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['projects-list'] })
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedUpload: vi.fn(),
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
    actionMenu?: (row: FileRecord) => { label: string; onClick: () => void }[]
    data: FileRecord[]
  }) => (
    <div>
      {data.map((file) => (
        <div key={file.id}>
          <span>{file.filename}</span>
          {actionMenu?.(file).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {file.id}:{item.label}
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
}))

vi.mock('@/components/ui/button', () => ({
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.File = dom.window.File
globalThis.FormData = dom.window.FormData
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedUpload } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import FileListPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedUploadMock = managedUpload as unknown as ReturnType<typeof vi.fn>

interface FileRecord {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  created_at: string
}

function fileRecord(id: string, filename: string): FileRecord {
  return {
    id,
    filename,
    content_type: 'text/plain',
    size_bytes: 3,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    archived_at: archivedAt,
  }
}

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('FileListPage upload lifecycle', () => {
  beforeEach(() => {
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedUploadMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo(null),
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
      currentProject: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('hides upload and delete actions when the current project is archived', async () => {
    managedGetMock.mockResolvedValue({
      data: [fileRecord('file-a', 'File A')],
      has_more: false,
    })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-archived',
      currentProject: {
        id: 'project-archived',
        org_id: 'org-a',
        name: 'Archived Project',
        slug: 'project-archived',
        is_default: false,
        archived_at: '2026-01-02T00:00:00Z',
      },
      organizations: [],
      projects: [],
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container, getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('File A')).toBeTruthy()
    })

    expect(queryByText('managed.files.upload')).toBeNull()
    expect(queryByText('file-a:common.delete')).toBeNull()
    expect(container.querySelector('input[type="file"]')).toBeNull()
  })

  it('does not continue a multi-file upload after the managed project changes', async () => {
    const firstUpload = deferred<void>()
    const uploadProjects: string[] = []
    managedUploadMock.mockImplementation(() => {
      uploadProjects.push(useProjectStore.getState().currentProjectId || '')
      if (uploadProjects.length === 1) return firstUpload.promise
      return Promise.resolve({})
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const firstFile = new File(['one'], 'one.txt', { type: 'text/plain' })
    const secondFile = new File(['two'], 'two.txt', { type: 'text/plain' })

    await act(async () => {
      fireEvent.change(input, {
        target: {
          files: [firstFile, secondFile],
        },
      })
    })

    expect(uploadProjects).toEqual(['project-a'])
    expect(managedUploadMock).toHaveBeenCalledWith('/files', expect.any(FormData), managedOptions())

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      firstUpload.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(uploadProjects).toEqual(['project-a'])
  })

  it('does not continue a multi-file upload after the current project is archived', async () => {
    const firstUpload = deferred<void>()
    const uploadedNames: string[] = []
    managedUploadMock.mockImplementation((_path: string, body: FormData) => {
      uploadedNames.push((body.get('file') as File).name)
      if (uploadedNames.length === 1) return firstUpload.promise
      return Promise.resolve({})
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const firstFile = new File(['one'], 'one.txt', { type: 'text/plain' })
    const secondFile = new File(['two'], 'two.txt', { type: 'text/plain' })

    await act(async () => {
      fireEvent.change(input, {
        target: {
          files: [firstFile, secondFile],
        },
      })
      await Promise.resolve()
    })

    expect(uploadedNames).toEqual(['one.txt'])

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      firstUpload.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(uploadedNames).toEqual(['one.txt'])
  })

  it('does not start an upload from an old file input after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const oldProjectFile = new File(['old project data'], 'old-project.txt', {
      type: 'text/plain',
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.change(input, {
        target: {
          files: [oldProjectFile],
        },
      })
      await Promise.resolve()
    })

    expect(managedUploadMock).not.toHaveBeenCalledWith(
      '/files',
      expect.any(FormData),
      managedOptions(),
    )
  })

  it('does not start an upload from an old file input after the current project is archived in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const archivedProjectFile = new File(['archived project data'], 'archived-project.txt', {
      type: 'text/plain',
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.change(input, {
        target: {
          files: [archivedProjectFile],
        },
      })
      await Promise.resolve()
    })

    expect(managedUploadMock).not.toHaveBeenCalledWith(
      '/files',
      expect.any(FormData),
      managedOptions(),
    )
  })

  it('does not invalidate files from an upload completion after the page unmounts', async () => {
    const upload = deferred<Record<string, never>>()
    managedUploadMock.mockReturnValueOnce(upload.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { container, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['one'], 'one.txt', { type: 'text/plain' })

    await act(async () => {
      fireEvent.change(input, {
        target: {
          files: [file],
        },
      })
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      upload.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['files', 'org-a:project-a'] })
  })

  it('does not invalidate files from an upload completion after the current project is archived', async () => {
    const upload = deferred<Record<string, never>>()
    managedUploadMock.mockReturnValueOnce(upload.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalled()
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['one'], 'one.txt', { type: 'text/plain' })

    await act(async () => {
      fireEvent.change(input, {
        target: {
          files: [file],
        },
      })
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      upload.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['files', 'org-a:project-a'] })
  })

  it('does not delete a file target that is no longer in the current files list', async () => {
    managedGetMock.mockResolvedValue({
      data: [fileRecord('file-a', 'File A')],
      has_more: false,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('File A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['files', 'org-a:project-a', '/files', undefined, false, 10], {
        data: [fileRecord('file-b', 'File B')],
        has_more: false,
      })
      fireEvent.click(getByText('file-a:common.delete'))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/files/file-a', managedOptions())
  })

  it('does not delete an old project file row after the managed project changes in the same tick', async () => {
    managedGetMock.mockResolvedValue({
      data: [fileRecord('file-a', 'Project A File')],
      has_more: false,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Project A File')).toBeTruthy()
    })

    const oldDeleteButton = getByText('file-a:common.delete')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/files/file-a', managedOptions())
  })

  it('does not delete a file from an old row action after the current project is archived', async () => {
    managedGetMock.mockResolvedValue({
      data: [fileRecord('file-a', 'Project A File')],
      has_more: false,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Project A File')).toBeTruthy()
    })

    const oldDeleteButton = getByText('file-a:common.delete')

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/files/file-a', managedOptions())
  })

  it('does not invalidate files from a delete completion after the page unmounts', async () => {
    const deleteFile = deferred<Record<string, never>>()
    managedGetMock.mockResolvedValue({
      data: [fileRecord('file-a', 'File A')],
      has_more: false,
    })
    managedDeleteMock.mockReturnValueOnce(deleteFile.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('File A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('file-a:common.delete'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      deleteFile.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['files', 'org-a:project-a'] })
  })

  it('does not invalidate files from a delete completion after the current project is archived', async () => {
    const deleteFile = deferred<Record<string, never>>()
    managedGetMock.mockResolvedValue({
      data: [fileRecord('file-a', 'File A')],
      has_more: false,
    })
    managedDeleteMock.mockReturnValueOnce(deleteFile.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <FileListPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('File A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('file-a:common.delete'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      deleteFile.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['files', 'org-a:project-a'] })
  })
})

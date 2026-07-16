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
  managedPut: vi.fn(),
}))

vi.mock('@/providers/permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    actionMenu,
    data,
  }: {
    actionMenu?: (row: OrganizationRecord) => { label: string; onClick: () => void }[]
    data: OrganizationRecord[]
  }) => (
    <div>
      {data.map((org) => (
        <div key={org.id}>
          <span>{org.name}</span>
          {actionMenu?.(org).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {org.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({ title, action }: { title: string; action?: ReactNode }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
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
  Input: ({
    autoFocus: _autoFocus,
    onChange,
    onKeyDown,
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
      onKeyDown={onKeyDown}
    />
  ),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedPost, managedPut } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import OrganizationPage from './page'

interface OrganizationRecord {
  id: string
  name: string
  slug: string
  role: string
  created_at?: string
}

interface OrganizationMemberRecord {
  id: string
  user_id: string
  organization_id: string
  role: string
  user_name?: string | null
  user_email?: string | null
}

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedPutMock = managedPut as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>

function meResponse(org: OrganizationRecord) {
  return {
    organization: org,
    organizations: [org],
  }
}

function member(userId: string, name: string): OrganizationMemberRecord {
  return {
    id: `member-${userId}`,
    user_id: userId,
    organization_id: 'org-a',
    role: 'admin',
    user_name: name,
    user_email: `${userId}@example.com`,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('OrganizationPage ownership transfer lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedDeleteMock.mockReset()
    managedPostMock.mockReset()
    managedPutMock.mockReset()
    managedDeleteMock.mockResolvedValue({})
    managedPostMock.mockResolvedValue({})
    managedPutMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return meResponse({
          id: 'org-a',
          name: 'Org A',
          slug: 'org-a',
          role: 'owner',
          created_at: '2026-01-01T00:00:00Z',
        })
      }
      if (path === '/organizations/org-a/members') {
        return { data: [member('user-a', 'User A')] }
      }
      return { data: [] }
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

  it('does not submit a transfer owner candidate that is no longer in the current member list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:manage.organization.transferOwnership'))
    })

    await waitFor(() => {
      expect(getByText('User A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('User A'))
    })

    await act(async () => {
      queryClient.setQueryData(['organization-members', 'org-a'], [member('user-b', 'User B')])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('User B')).toBeTruthy()
    })

    const transferButtons = getAllByRole('button', {
      name: /manage\.organization\.transferOwnership/,
    })
    await act(async () => {
      fireEvent.click(transferButtons[transferButtons.length - 1])
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/organizations/org-a/transfer-ownership', {
      new_owner_user_id: 'user-a',
    })
  })

  it('does not submit a transfer owner candidate that leaves the current member list during confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:manage.organization.transferOwnership'))
    })

    await waitFor(() => {
      expect(getByText('User A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('User A'))
    })

    await act(async () => {
      queryClient.setQueryData(['organization-members', 'org-a'], [member('user-b', 'User B')])
      const transferButtons = getAllByRole('button', {
        name: /manage\.organization\.transferOwnership/,
      })
      fireEvent.click(transferButtons[transferButtons.length - 1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/organizations/org-a/transfer-ownership', {
      new_owner_user_id: 'user-a',
    })
  })

  it('refetches organization data instead of applying stale auth-me after org context changes', async () => {
    const oldAuthMe = deferred<ReturnType<typeof meResponse>>()
    managedGetMock.mockImplementation((path: string) => {
      if (path === 'auth/me') {
        const orgId = useProjectStore.getState().currentOrgId
        if (orgId === 'org-b') {
          return Promise.resolve(
            meResponse({
              id: 'org-b',
              name: 'Org B',
              slug: 'org-b',
              role: 'owner',
              created_at: '2026-01-02T00:00:00Z',
            }),
          )
        }
        return oldAuthMe.promise
      }
      return Promise.resolve({ data: [] })
    })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
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

    const view = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(managedGetMock).toHaveBeenCalledWith('auth/me'))

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      view.rerender(
        <QueryClientProvider client={queryClient}>
          <OrganizationPage />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })

    await waitFor(() => expect(view.getByText('Org B')).toBeTruthy())

    await act(async () => {
      oldAuthMe.resolve(
        meResponse({
          id: 'org-a',
          name: 'Org A',
          slug: 'org-a',
          role: 'owner',
          created_at: '2026-01-01T00:00:00Z',
        }),
      )
      await Promise.resolve()
    })

    expect(view.getByText('Org B')).toBeTruthy()
    expect(view.queryByText('Org A')).toBeNull()
  })

  it('ignores an older organization switch response that resolves after a newer switch', async () => {
    const organizations: OrganizationRecord[] = [
      {
        id: 'org-a',
        name: 'Org A',
        slug: 'org-a',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'org-b',
        name: 'Org B',
        slug: 'org-b',
        role: 'owner',
        created_at: '2026-01-02T00:00:00Z',
      },
      {
        id: 'org-c',
        name: 'Org C',
        slug: 'org-c',
        role: 'owner',
        created_at: '2026-01-03T00:00:00Z',
      },
    ]
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: organizations[0],
          organizations,
        }
      }
      return { data: [] }
    })

    const firstSwitch = deferred<{ org_id: string; project_id: string }>()
    const secondSwitch = deferred<{ org_id: string; project_id: string }>()
    managedPostMock
      .mockReturnValueOnce(firstSwitch.promise)
      .mockReturnValueOnce(secondSwitch.promise)

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
    })

    const { getAllByText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org C')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:manage.organization.switch'))
      fireEvent.click(getByText('org-c:manage.organization.switch'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenNthCalledWith(
      1,
      'auth/switch-context',
      { org_id: 'org-b' },
      { skipManagedContext: true, headers: { 'X-Org-Id': 'org-b' } },
    )
    expect(managedPostMock).toHaveBeenNthCalledWith(
      2,
      'auth/switch-context',
      { org_id: 'org-c' },
      { skipManagedContext: true, headers: { 'X-Org-Id': 'org-c' } },
    )

    await act(async () => {
      secondSwitch.resolve({ org_id: 'org-c', project_id: 'project-c' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(useProjectStore.getState().currentOrgId).toBe('org-c')
      expect(useProjectStore.getState().currentProjectId).toBe('project-c')
    })

    await act(async () => {
      firstSwitch.resolve({ org_id: 'org-b', project_id: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledTimes(2)
    })
    expect(useProjectStore.getState().currentOrgId).toBe('org-c')
    expect(useProjectStore.getState().currentProjectId).toBe('project-c')
  })

  it('stores switched organization project metadata from the switch-context response', async () => {
    const organizations: OrganizationRecord[] = [
      {
        id: 'org-a',
        name: 'Org A',
        slug: 'org-a',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'org-b',
        name: 'Org B',
        slug: 'org-b',
        role: 'owner',
        created_at: '2026-01-02T00:00:00Z',
      },
    ]
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: organizations[0],
          organizations,
        }
      }
      return { data: [] }
    })
    managedPostMock.mockResolvedValueOnce({
      org_id: 'org-b',
      project_id: 'project-b',
      project: {
        id: 'project-b',
        org_id: 'org-b',
        name: 'Project B',
        slug: 'project-b',
        is_default: true,
        archived_at: null,
      },
      projects: [
        {
          id: 'project-b',
          org_id: 'org-b',
          name: 'Project B',
          slug: 'project-b',
          is_default: true,
          archived_at: null,
        },
      ],
    })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: true,
      },
      organizations,
      projects: [
        {
          id: 'project-a',
          org_id: 'org-a',
          name: 'Project A',
          slug: 'project-a',
          is_default: true,
        },
      ],
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
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:manage.organization.switch'))
      await Promise.resolve()
    })

    expect(useProjectStore.getState().currentOrgId).toBe('org-b')
    expect(useProjectStore.getState().currentProjectId).toBe('project-b')
    expect(useProjectStore.getState().currentProject?.name).toBe('Project B')
    expect(useProjectStore.getState().projects.map((project) => project.id)).toEqual(['project-b'])
  })

  it('does not close a reopened create organization dialog when an older create finishes', async () => {
    const create = deferred<{ id: string; name: string; slug: string }>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Old Org' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.create').at(-1)!)
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'New Org' },
      })
    })

    await act(async () => {
      create.resolve({ id: 'org-old', name: 'Old Org', slug: 'old-org' })
      await Promise.resolve()
    })

    expect(
      (getByPlaceholderText('manage.organization.namePlaceholder') as HTMLInputElement).value,
    ).toBe('New Org')
  })

  it('does not close a reopened edit organization dialog when an older edit finishes', async () => {
    const update = deferred<Record<string, never>>()
    managedPutMock.mockReturnValueOnce(update.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Old Org Name' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('common.save'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'New Org Name' },
      })
    })

    await act(async () => {
      update.resolve({})
      await Promise.resolve()
    })

    expect(
      (getByPlaceholderText('manage.organization.namePlaceholder') as HTMLInputElement).value,
    ).toBe('New Org Name')
  })

  it('does not submit an organization edit after the target is no longer editable', async () => {
    const ownerOrg: OrganizationRecord = {
      id: 'org-a',
      name: 'Org A',
      slug: 'org-a',
      role: 'owner',
      created_at: '2026-01-01T00:00:00Z',
    }
    const memberOrg: OrganizationRecord = { ...ownerOrg, role: 'member' }
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') return meResponse(ownerOrg)
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Edited Org' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(['auth-me', null, null], meResponse(memberOrg))
      fireEvent.click(getByText('common.save'))
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalledWith('/organizations/org-a', {
      name: 'Edited Org',
    })
  })

  it('does not create an organization from old dialog state in the same turn as an org switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Old Dialog Org' },
      })
    })

    const createButton = getAllByText('manage.organization.create').at(-1)!

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(createButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('auth/organizations', {
      name: 'Old Dialog Org',
    })
  })

  it('does not edit an organization from old dialog state in the same turn as an org switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Old Org Name' },
      })
    })

    const saveButton = getByText('common.save')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalledWith('/organizations/org-a', {
      name: 'Old Org Name',
    })
  })

  it('does not delete an organization from old confirmation state in the same turn as an org switch', async () => {
    const organizations: OrganizationRecord[] = [
      {
        id: 'org-a',
        name: 'Org A',
        slug: 'org-a',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'org-b',
        name: 'Org B',
        slug: 'org-b',
        role: 'owner',
        created_at: '2026-01-02T00:00:00Z',
      },
    ]
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: organizations[0],
          organizations,
        }
      }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:common.delete'))
    })

    const deleteButton = getAllByText('manage.organization.delete').at(-1)!

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-c', currentProjectId: 'project-c' })
      fireEvent.click(deleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/organizations/org-b')
  })

  it('does not transfer ownership from old dialog state in the same turn as an org switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:manage.organization.transferOwnership'))
    })

    await waitFor(() => {
      expect(getByText('User A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('User A'))
    })

    const transferButtons = getAllByRole('button', {
      name: /manage\.organization\.transferOwnership/,
    })
    const transferButton = transferButtons[transferButtons.length - 1]

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(transferButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/organizations/org-a/transfer-ownership', {
      new_owner_user_id: 'user-a',
    })
  })

  it('does not let an edit completion close a dialog reopened after auth data invalidated the old target', async () => {
    const update = deferred<Record<string, never>>()
    managedPutMock.mockReturnValueOnce(update.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const ownerOrg = {
      id: 'org-a',
      name: 'Org A',
      slug: 'org-a',
      role: 'owner',
      created_at: '2026-01-01T00:00:00Z',
    }
    const memberOrg = { ...ownerOrg, role: 'member' }
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') return meResponse(ownerOrg)
      return { data: [] }
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Old Org Name' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('common.save'))
      await Promise.resolve()
    })

    await act(async () => {
      queryClient.setQueryData(['auth-me'], meResponse(memberOrg))
      await Promise.resolve()
    })

    await act(async () => {
      queryClient.setQueryData(['auth-me'], meResponse(ownerOrg))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:common.edit'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'New Org Name' },
      })
    })

    await act(async () => {
      update.resolve({})
      await Promise.resolve()
    })

    expect(
      (getByPlaceholderText('manage.organization.namePlaceholder') as HTMLInputElement).value,
    ).toBe('New Org Name')
  })

  it('does not close a reopened transfer ownership dialog when an older transfer finishes', async () => {
    const transfer = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(transfer.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:manage.organization.transferOwnership'))
    })

    await waitFor(() => {
      expect(getByText('User A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('User A'))
    })

    await act(async () => {
      const transferButtons = getAllByRole('button', {
        name: /manage\.organization\.transferOwnership/,
      })
      fireEvent.click(transferButtons[transferButtons.length - 1])
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:manage.organization.transferOwnership'))
    })

    await waitFor(() => {
      expect(getByText('User A')).toBeTruthy()
    })

    await act(async () => {
      transfer.resolve({})
      await Promise.resolve()
    })

    expect(getByText('User A')).toBeTruthy()
  })

  it('does not close a reopened delete organization dialog when an older delete finishes', async () => {
    const organizations: OrganizationRecord[] = [
      {
        id: 'org-a',
        name: 'Org A',
        slug: 'org-a',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'org-b',
        name: 'Org B',
        slug: 'org-b',
        role: 'owner',
        created_at: '2026-01-02T00:00:00Z',
      },
    ]
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: organizations[0],
          organizations,
        }
      }
      return { data: [] }
    })
    const remove = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(remove.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:common.delete'))
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.delete').at(-1)!)
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:common.delete'))
    })

    await act(async () => {
      remove.resolve({})
      await Promise.resolve()
    })

    expect(getAllByText('manage.organization.delete').length).toBeGreaterThan(0)
  })

  it('does not delete an organization target that leaves the current organization list during confirmation', async () => {
    const orgA: OrganizationRecord = {
      id: 'org-a',
      name: 'Org A',
      slug: 'org-a',
      role: 'owner',
      created_at: '2026-01-01T00:00:00Z',
    }
    const orgB: OrganizationRecord = {
      id: 'org-b',
      name: 'Org B',
      slug: 'org-b',
      role: 'owner',
      created_at: '2026-01-02T00:00:00Z',
    }
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: orgA,
          organizations: [orgA, orgB],
        }
      }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:common.delete'))
    })

    await act(async () => {
      queryClient.setQueryData(['auth-me', null, null], {
        organization: orgA,
        organizations: [orgA],
      })
      fireEvent.click(getAllByText('manage.organization.delete').at(-1)!)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/organizations/org-b')
  })

  it('does not invalidate auth data from a create organization completion after the page unmounts', async () => {
    const create = deferred<{ id: string; name: string; slug: string }>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByText, getByPlaceholderText, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.create')[0])
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('manage.organization.namePlaceholder'), {
        target: { value: 'Unmounted Org' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.create').at(-1)!)
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      create.resolve({ id: 'org-created', name: 'Unmounted Org', slug: 'unmounted-org' })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['auth-me'] })
  })

  it('does not invalidate auth data from a delete organization completion after the page unmounts', async () => {
    const organizations: OrganizationRecord[] = [
      {
        id: 'org-a',
        name: 'Org A',
        slug: 'org-a',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'org-b',
        name: 'Org B',
        slug: 'org-b',
        role: 'owner',
        created_at: '2026-01-02T00:00:00Z',
      },
    ]
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: organizations[0],
          organizations,
        }
      }
      return { data: [] }
    })
    const remove = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(remove.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByText, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:common.delete'))
    })

    await act(async () => {
      fireEvent.click(getAllByText('manage.organization.delete').at(-1)!)
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      remove.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['auth-me'] })
  })

  it('does not invalidate auth data from a transfer ownership completion after the page unmounts', async () => {
    const transfer = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(transfer.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-a:manage.organization.transferOwnership'))
    })

    await waitFor(() => {
      expect(getByText('User A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('User A'))
    })

    await act(async () => {
      const transferButtons = getAllByRole('button', {
        name: /manage\.organization\.transferOwnership/,
      })
      fireEvent.click(transferButtons[transferButtons.length - 1])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      transfer.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['auth-me'] })
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['organization-members'] })
  })

  it('does not switch organizations from a switch response after the page unmounts', async () => {
    const organizations: OrganizationRecord[] = [
      {
        id: 'org-a',
        name: 'Org A',
        slug: 'org-a',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'org-b',
        name: 'Org B',
        slug: 'org-b',
        role: 'owner',
        created_at: '2026-01-02T00:00:00Z',
      },
    ]
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/me') {
        return {
          organization: organizations[0],
          organizations,
        }
      }
      return { data: [] }
    })
    const switchOrg = deferred<{ org_id: string; project_id: string }>()
    managedPostMock.mockReturnValueOnce(switchOrg.promise)
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
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

    const { getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <OrganizationPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('org-b:manage.organization.switch'))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      switchOrg.resolve({ org_id: 'org-b', project_id: 'project-b' })
      await Promise.resolve()
    })

    expect(useProjectStore.getState().currentOrgId).toBe('org-a')
    expect(useProjectStore.getState().currentProjectId).toBe('project-a')
  })
})

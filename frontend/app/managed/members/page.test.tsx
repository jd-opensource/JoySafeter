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
  managedPost: vi.fn(),
  managedPut: vi.fn(),
}))

type MockAuthUser = {
  id: string
  email: string
  name: string
  emailVerified: boolean
  isSuperUser: boolean
}

type AuthMockGlobal = typeof globalThis & {
  __joysafeterAuthMockUser?: MockAuthUser | null
  __joysafeterAuthClientMock?: {
    forgetPassword?: (...args: unknown[]) => unknown
    signInEmail?: (...args: unknown[]) => unknown
    signUpEmail?: (...args: unknown[]) => unknown
  }
}

const defaultAuthUser = (): MockAuthUser => ({
  id: 'user-current',
  email: 'current@example.com',
  name: 'Current User',
  emailVerified: true,
  isSuperUser: false,
})

function setMockAuthUser(user: MockAuthUser | null) {
  ;(globalThis as AuthMockGlobal).__joysafeterAuthMockUser = user
}

function getMockAuthUser() {
  return (globalThis as AuthMockGlobal).__joysafeterAuthMockUser ?? null
}

function getMockAuthClient() {
  return (globalThis as AuthMockGlobal).__joysafeterAuthClientMock
}

vi.mock('@/lib/auth/auth-client', () => ({
  __setMockSessionUser: (user: MockAuthUser | null) => {
    setMockAuthUser(user)
  },
  client: {
    forgetPassword: (...args: unknown[]) =>
      getMockAuthClient()?.forgetPassword?.(...args) ?? Promise.resolve({}),
    signIn: {
      email: (...args: unknown[]) =>
        getMockAuthClient()?.signInEmail?.(...args) ?? Promise.resolve({}),
    },
    signUp: {
      email: (...args: unknown[]) =>
        getMockAuthClient()?.signUpEmail?.(...args) ?? Promise.resolve({}),
    },
  },
  useSession: () => ({
    data: getMockAuthUser() ? { user: getMockAuthUser() } : null,
    isPending: false,
    error: null,
    refetch: async () => {},
  }),
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
    actionMenu?: (row: MemberRecord) => { label: string; onClick: () => void }[]
    data: MemberRecord[]
  }) => (
    <div>
      {data.map((row) => (
        <div key={row.email}>
          <span>{row.display_name}</span>
          <span>{row.email}</span>
          {actionMenu?.(row).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {row.user_id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
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
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedPost, managedPut } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import MembersPage from './page'

interface MemberRecord {
  user_id: string
  email: string
  display_name: string
  role: string
  joined_at?: string
}

function member(userId: string, displayName: string): MemberRecord {
  return {
    user_id: userId,
    email: `${userId}@example.com`,
    display_name: displayName,
    role: 'developer',
    joined_at: '2026-01-01T00:00:00Z',
  }
}

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedPutMock = managedPut as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('MembersPage invite search lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setMockAuthUser(defaultAuthUser())
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
    })
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedDeleteMock.mockReset()
    managedPutMock.mockReset()
    managedPostMock.mockResolvedValue({
      user_id: 'user-invited',
      email: 'candidate@example.com',
      display_name: 'Candidate',
      role: 'developer',
    })
    managedDeleteMock.mockResolvedValue({})
    managedPutMock.mockResolvedValue(member('user-a', 'Member A'))
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/members') return []
      if (String(path).startsWith('/auth/search-users')) {
        return [
          {
            id: 'user-stale',
            email: 'stale@example.com',
            name: 'Stale User',
            already_member: false,
          },
        ]
      }
      return []
    })
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('refetches members instead of reusing the previous organization member list', async () => {
    vi.useRealTimers()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path !== 'auth/members') return []
      const orgId = useProjectStore.getState().currentOrgId
      return orgId === 'org-b'
        ? [
            {
              user_id: 'user-b',
              email: 'b@example.com',
              display_name: 'Org B Member',
              role: 'developer',
            },
          ]
        : [
            {
              user_id: 'user-a',
              email: 'a@example.com',
              display_name: 'Org A Member',
              role: 'developer',
            },
          ]
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText, queryByText, rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A Member')).toBeTruthy()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <MembersPage />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(getByText('Org B Member')).toBeTruthy()
    })
    expect(queryByText('Org A Member')).toBeNull()
  })

  it('keeps the org-level invite draft when only the managed project changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByDisplayValue, getByPlaceholderText, getByText, rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'candidate@example.com' },
      })
    })

    expect(getByDisplayValue('candidate@example.com')).toBeTruthy()

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      rerender(
        <QueryClientProvider client={queryClient}>
          <MembersPage />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })

    expect(getByDisplayValue('candidate@example.com')).toBeTruthy()
  })

  it('does not show delayed invite search results after the invite dialog is closed and reopened', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'stale' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      vi.advanceTimersByTime(300)
      await Promise.resolve()
    })

    expect(managedGetMock).not.toHaveBeenCalledWith('/auth/search-users?q=stale&limit=5')

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    expect(queryByText('Stale User')).toBeNull()
    expect(queryByText('stale@example.com')).toBeNull()
  })

  it('ignores invite search responses that finish after the invite dialog is closed', async () => {
    let resolveSearch:
      | ((
          value: {
            id: string
            email: string
            name: string
            already_member: boolean
          }[],
        ) => void)
      | undefined

    managedGetMock.mockImplementation((path: string) => {
      if (path === 'auth/members') return Promise.resolve([])
      if (String(path).startsWith('/auth/search-users')) {
        return new Promise((resolve) => {
          resolveSearch = resolve
        })
      }
      return Promise.resolve([])
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText, queryByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'stale' },
      })
    })

    await act(async () => {
      vi.advanceTimersByTime(300)
      await Promise.resolve()
    })

    expect(managedGetMock).toHaveBeenCalledWith('/auth/search-users?q=stale&limit=5')

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      resolveSearch?.([
        {
          id: 'user-stale',
          email: 'stale@example.com',
          name: 'Stale User',
          already_member: false,
        },
      ])
      await Promise.resolve()
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    expect(queryByText('Stale User')).toBeNull()
    expect(queryByText('stale@example.com')).toBeNull()
  })

  it('does not close a reopened invite dialog when an older invite finishes', async () => {
    vi.useRealTimers()
    const invite = deferred<{
      user_id: string
      email: string
      display_name: string
      role: string
    }>()
    managedPostMock.mockReturnValueOnce(invite.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByDisplayValue, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'old@example.com' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: 'manage.members.invite' })[1])
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('dialog-close'))
    })

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'new@example.com' },
      })
    })

    await act(async () => {
      invite.resolve({
        user_id: 'user-invited',
        email: 'old@example.com',
        display_name: 'Old Invite',
        role: 'developer',
      })
      await Promise.resolve()
    })

    expect(getByDisplayValue('new@example.com')).toBeTruthy()
  })

  it('does not invite an email that is already in the current member list', async () => {
    vi.useRealTimers()
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'candidate@example.com' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(['org-members', 'org-a'], [
        {
          ...member('user-candidate', 'Candidate'),
          email: 'candidate@example.com',
        },
      ])
      fireEvent.click(getAllByRole('button', { name: 'manage.members.invite' })[1])
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('auth/members/invite', {
      email: 'candidate@example.com',
      role: 'developer',
    })
  })

  it('does not invite from an old organization dialog after the organization changes in the same tick', async () => {
    vi.useRealTimers()
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getAllByRole, getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'project-a-operator@example.com' },
      })
    })

    const oldInviteButton = getAllByRole('button', { name: 'manage.members.invite' })[1]

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(oldInviteButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('auth/members/invite', {
      email: 'project-a-operator@example.com',
      role: 'developer',
    })
  })

  it('does not send delayed invite search from an old organization after the organization changes', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'stale-search' },
      })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      vi.advanceTimersByTime(300)
      await Promise.resolve()
    })

    expect(managedGetMock).not.toHaveBeenCalledWith(
      '/auth/search-users?q=stale-search&limit=5',
    )
  })

  it('does not close a new remove confirmation when an older remove finishes', async () => {
    vi.useRealTimers()
    const remove = deferred<Record<string, never>>()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/members') return [member('user-a', 'Member A'), member('user-b', 'Member B')]
      return []
    })
    managedDeleteMock.mockReturnValueOnce(remove.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Member A')).toBeTruthy()
      expect(getByText('Member B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('user-a:manage.members.remove'))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.cancel' }))
    })

    await act(async () => {
      fireEvent.click(getByText('user-b:manage.members.remove'))
    })

    await act(async () => {
      remove.resolve({})
      await Promise.resolve()
    })

    expect(getByRole('button', { name: 'common.cancel' })).toBeTruthy()
  })

  it('does not remove a member that leaves the current member list during confirmation', async () => {
    vi.useRealTimers()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/members') return [member('user-a', 'Member A')]
      return []
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Member A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('user-a:manage.members.remove'))
    })

    await act(async () => {
      queryClient.setQueryData(['org-members', 'org-a'], [member('user-b', 'Member B')])
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('auth/members/user-a')
  })

  it('does not remove an old organization member after the organization changes in the same tick', async () => {
    vi.useRealTimers()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/members') return [member('user-a', 'Org A Member')]
      return []
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByRole, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Org A Member')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('user-a:manage.members.remove'))
    })

    const oldRemoveButton = getByRole('button', { name: 'common.delete' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-b', currentProjectId: 'project-b' })
      fireEvent.click(oldRemoveButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('auth/members/user-a')
  })

  it('does not invalidate members from an invite completion after the page unmounts', async () => {
    vi.useRealTimers()
    const invite = deferred<{
      user_id: string
      email: string
      display_name: string
      role: string
    }>()
    managedPostMock.mockReturnValueOnce(invite.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getAllByRole, getByPlaceholderText, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      fireEvent.click(getByText('manage.members.invite'))
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('user@example.com'), {
        target: { value: 'candidate@example.com' },
      })
    })

    await act(async () => {
      fireEvent.click(getAllByRole('button', { name: 'manage.members.invite' })[1])
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      invite.resolve({
        user_id: 'user-invited',
        email: 'candidate@example.com',
        display_name: 'Candidate',
        role: 'developer',
      })
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['org-members'] })
  })

  it('does not invalidate members from a remove completion after the page unmounts', async () => {
    vi.useRealTimers()
    const remove = deferred<Record<string, never>>()
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === 'auth/members') return [member('user-a', 'Member A')]
      return []
    })
    managedDeleteMock.mockReturnValueOnce(remove.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const { getByRole, getByText, unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MembersPage />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Member A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('user-a:manage.members.remove'))
    })

    await act(async () => {
      fireEvent.click(getByRole('button', { name: 'common.delete' }))
      await Promise.resolve()
    })

    unmount()

    await act(async () => {
      remove.resolve({})
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['org-members'] })
  })
})

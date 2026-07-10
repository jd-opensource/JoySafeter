import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import React, { type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  FieldHelp: () => null,
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

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
}))

const SelectContext = React.createContext<(value: string) => void>(() => {})

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children: ReactNode
    onValueChange?: (value: string) => void
    value?: string
  }) => (
    <SelectContext.Provider value={onValueChange ?? (() => {})}>
      <div data-testid={value ? `select-${value}` : undefined}>{children}</div>
    </SelectContext.Provider>
  ),
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => {
    const onValueChange = React.useContext(SelectContext)
    return (
      <button type="button" onClick={() => onValueChange(value)}>
        {children}
      </button>
    )
  },
  SelectLabel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedGet, managedPost } from '@/lib/api-client'
import { clearNonSessionQueryData } from '@/lib/query-client-lifecycle'
import { useProjectStore } from '@/stores/managed/project-store'

import { CreateSessionDialog } from './create-session-dialog'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

describe('CreateSessionDialog managed object lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
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

  it('refetches selectable resources instead of reusing the previous project data', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents') return { data: [{ id: 'agent_a', name: 'Agent A', engine_kind: 'claude' }] }
      if (path === '/environments') return { data: [] }
      if (path === '/vaults') return { data: [] }
      if (path === '/files?limit=100') return { data: [] }
      if (path === '/memory_stores?limit=100') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <CreateSessionDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/agents')
    })
    const agentCallsBeforeSwitch = managedGetMock.mock.calls.filter(([path]) => path === '/agents')
    expect(agentCallsBeforeSwitch).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      const agentCalls = managedGetMock.mock.calls.filter(([path]) => path === '/agents')
      expect(agentCalls).toHaveLength(2)
    })
  })

  it('does not submit an agent selected from the previous project after managed context data changes', async () => {
    let projectAgent = { id: 'agent_a', name: 'Agent A', engine_kind: 'claude' }
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents') return { data: [projectAgent] }
      if (path === '/environments') return { data: [] }
      if (path === '/vaults') return { data: [] }
      if (path === '/files?limit=100') return { data: [] }
      if (path === '/memory_stores?limit=100') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'sess_created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateSessionDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      getByText('Agent A').click()
    })

    await waitFor(() => {
      expect(document.querySelector('[data-testid="select-agent_a"]')).toBeTruthy()
    })

    projectAgent = { id: 'agent_b', name: 'Agent B', engine_kind: 'claude' }
    await act(async () => {
      clearNonSessionQueryData(queryClient)
    })

    await waitFor(() => {
      expect(getByText('Agent B')).toBeTruthy()
    })

    await waitFor(() => {
      expect(
        (getByText('managed.sessions.create.submit') as HTMLButtonElement).disabled,
      ).toBe(true)
    })

    fireEvent.click(getByText('managed.sessions.create.submit'))

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not submit an agent that leaves the current selectable agents in the same turn as submit', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents') return { data: [{ id: 'agent_a', name: 'Agent A', engine_kind: 'claude' }] }
      if (path === '/environments') return { data: [] }
      if (path === '/vaults') return { data: [] }
      if (path === '/files?limit=100') return { data: [] }
      if (path === '/memory_stores?limit=100') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'sess_created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateSessionDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      getByText('Agent A').click()
    })

    await waitFor(() => {
      expect(document.querySelector('[data-testid="select-agent_a"]')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['agents-for-session', 'org-a:project-a'], [
        { id: 'agent_b', name: 'Agent B', engine_kind: 'claude' },
      ])
      fireEvent.click(getByText('managed.sessions.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not submit selected resources from old dialog state in the same turn as a project switch', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents') {
        return { data: [{ id: 'agent_a', name: 'Agent A', engine_kind: 'claude' }] }
      }
      if (path === '/environments') {
        return { data: [{ id: 'env_a', name: 'Env A', archived_at: null }] }
      }
      if (path === '/vaults') {
        return { data: [{ id: 'vault_a', name: 'Vault A', archived_at: null }] }
      }
      if (path === '/files?limit=100') {
        return {
          data: [
            {
              id: 'file_a',
              filename: 'dataset.json',
              purpose: 'assistants',
              content_type: 'application/json',
              size_bytes: 512,
              downloadable: true,
              created_at: '2026-07-10T00:00:00Z',
            },
          ],
        }
      }
      if (path === '/memory_stores?limit=100') {
        return { data: [{ id: 'mem_a', name: 'Memory A', archived_at: null }] }
      }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'sess_created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateSessionDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
      expect(getByText('Env A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('Agent A'))
      fireEvent.click(getByText('Env A'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.sessions.create.selectVaults'))
      await Promise.resolve()
    })
    await waitFor(() => {
      expect(getByText('Vault A')).toBeTruthy()
    })
    await act(async () => {
      fireEvent.click(getByText('Vault A'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.sessions.create.addResource'))
      await Promise.resolve()
    })
    await waitFor(() => {
      expect(getByText('dataset.json')).toBeTruthy()
    })
    await act(async () => {
      fireEvent.click(getByText('dataset.json'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.sessions.create.addMemoryStore'))
      await Promise.resolve()
    })
    await waitFor(() => {
      expect(getByText('Memory A')).toBeTruthy()
    })
    await act(async () => {
      fireEvent.click(getByText('Memory A'))
      await Promise.resolve()
    })

    const submitButton = getByText('managed.sessions.create.submit') as HTMLButtonElement
    expect(submitButton.disabled).toBe(false)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(submitButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions', expect.anything())
  })

  it('ignores a stale create completion after the managed project changes', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents') return { data: [{ id: 'agent_a', name: 'Agent A', engine_kind: 'claude' }] }
      if (path === '/environments') return { data: [] }
      if (path === '/vaults') return { data: [] }
      if (path === '/files?limit=100') return { data: [] }
      if (path === '/memory_stores?limit=100') return { data: [] }
      return { data: [] }
    })
    let resolveCreate: (value: { id: string }) => void = () => {}
    managedPostMock.mockImplementation(
      () =>
        new Promise<{ id: string }>((resolve) => {
          resolveCreate = resolve
        }),
    )
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const onOpenChange = vi.fn()
    const onCreated = vi.fn()

    const { getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateSessionDialog open onOpenChange={onOpenChange} onCreated={onCreated} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      getByText('Agent A').click()
    })

    fireEvent.click(getByText('managed.sessions.create.submit'))

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'a' })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      resolveCreate({ id: 'sess_created' })
      await Promise.resolve()
    })

    expect(onOpenChange).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('ignores a stale create completion after the dialog unmounts', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents') return { data: [{ id: 'agent_a', name: 'Agent A', engine_kind: 'claude' }] }
      if (path === '/environments') return { data: [] }
      if (path === '/vaults') return { data: [] }
      if (path === '/files?limit=100') return { data: [] }
      if (path === '/memory_stores?limit=100') return { data: [] }
      return { data: [] }
    })
    let resolveCreate: (value: { id: string }) => void = () => {}
    managedPostMock.mockImplementation(
      () =>
        new Promise<{ id: string }>((resolve) => {
          resolveCreate = resolve
        }),
    )
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const onOpenChange = vi.fn()
    const onCreated = vi.fn()

    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateSessionDialog open onOpenChange={onOpenChange} onCreated={onCreated} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(view.getByText('Agent A')).toBeTruthy()
    })

    await act(async () => {
      view.getByText('Agent A').click()
    })

    fireEvent.click(view.getByText('managed.sessions.create.submit'))

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'a' })
    })

    view.unmount()

    await act(async () => {
      resolveCreate({ id: 'sess_created_after_unmount' })
      await Promise.resolve()
    })

    expect(onOpenChange).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
  })
})

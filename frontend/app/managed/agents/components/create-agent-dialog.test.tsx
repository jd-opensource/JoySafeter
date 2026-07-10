import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
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
  SkillVersionSelect: () => null,
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
    <input {...props} onChange={onChange} onInput={onChange as React.FormEventHandler<HTMLInputElement>} />
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    value,
    onValueChange,
  }: {
    children: ReactNode
    value?: string
    onValueChange?: (value: string) => void
  }) => {
    const wireItems = (nodes: ReactNode): ReactNode =>
      Children.map(nodes, (child) => {
        if (!isValidElement(child)) return child
        return cloneElement(child as ReactElement<{ children?: ReactNode; onSelectValue?: (value: string) => void }>, {
          onSelectValue: onValueChange,
          children: wireItems((child.props as { children?: ReactNode }).children),
        })
      })
    return <div data-testid={value ? `select-${value}` : undefined}>{wireItems(children)}</div>
  },
  SelectContent: ({
    children,
    onSelectValue,
  }: {
    children: ReactNode
    onSelectValue?: (value: string) => void
  }) => (
    <div>
      {Children.map(children, (child) =>
        isValidElement(child)
          ? cloneElement(child as ReactElement<{ onSelectValue?: (value: string) => void }>, {
              onSelectValue,
            })
          : child,
      )}
    </div>
  ),
  SelectItem: ({
    children,
    value,
    onSelectValue,
  }: {
    children: ReactNode
    value: string
    onSelectValue?: (value: string) => void
  }) => (
    <button type="button" onClick={() => onSelectValue?.(value)}>
      {children}
    </button>
  ),
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

import { CreateAgentDialog } from './create-agent-dialog'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('CreateAgentDialog managed object lifecycle', () => {
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

  it('refetches selectable dependencies instead of reusing previous project data', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') return { data: [{ id: 'skill-a', name: 'Skill A', latest_version: '1.0.0' }] }
      if (path === '/environments') return { data: [{ id: 'env-a', name: 'Env A' }] }
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
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/secrets')
      expect(managedGetMock).toHaveBeenCalledWith('/skills')
      expect(managedGetMock).toHaveBeenCalledWith('/environments')
    })
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets')).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/skills')).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments')).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets')).toHaveLength(2)
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/skills')).toHaveLength(2)
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments')).toHaveLength(2)
    })
  })

  it('does not submit a secret selected from the previous project after managed context data changes', async () => {
    let secretName = 'secret-a'
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') {
        return { data: [{ name: secretName }] }
      }
      if (path === '/skills') {
        return { data: [] }
      }
      if (path === '/environments') {
        return { data: [] }
      }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'agent-created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/secrets')
      expect(getByText('secret-a')).toBeTruthy()
    })

    await waitFor(() => {
      expect(document.querySelector('[data-testid="select-secret-a"]')).toBeTruthy()
    })

    secretName = 'secret-b'
    await act(async () => {
      clearNonSessionQueryData(queryClient)
    })

    await waitFor(() => {
      const secretCalls = managedGetMock.mock.calls.filter(([path]) => path === '/secrets')
      expect(secretCalls.length).toBeGreaterThan(1)
      expect(getByText('secret-b')).toBeTruthy()
    })

    const nameInput = getByPlaceholderText(
      'managed.agents.create.namePlaceholder',
    ) as HTMLInputElement
    await act(async () => {
      nameInput.value = 'Created Agent'
      fireEvent.input(nameInput, {
        target: { value: 'Created Agent' },
      })
    })

    await waitFor(() => {
      expect(
        (getByText('managed.agents.create.submit') as HTMLButtonElement).disabled,
      ).toBe(false)
    })

    await act(async () => {
      getByText('managed.agents.create.submit').click()
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)
    expect(managedPostMock.mock.calls[0][1]).toMatchObject({
      name: 'Created Agent',
      secret_ref: 'secret-b',
    })
  })

  it('does not submit a default secret after the user chooses no selection', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'agent-created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('secret-a')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.agents.edit.noSelection'))
      fireEvent.input(getByPlaceholderText('managed.agents.create.namePlaceholder'), {
        target: { value: 'Agent without secret' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)
    expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('secret_ref')
  })

  it('does not submit a default secret after it leaves the current selectable secret list', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'agent-created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('secret-a')).toBeTruthy()
    })

    await act(async () => {
      const nameInput = getByPlaceholderText(
        'managed.agents.create.namePlaceholder',
      ) as HTMLInputElement
      nameInput.value = 'Agent without stale secret'
      fireEvent.input(nameInput, {
        target: { value: 'Agent without stale secret' },
      })
    })

    await waitFor(() => {
      expect(
        (getByText('managed.agents.create.submit') as HTMLButtonElement).disabled,
      ).toBe(false)
    })

    await act(async () => {
      queryClient.setQueryData(['secrets', 'org-a:project-a'], { data: [] })
      fireEvent.click(getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)
    expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('secret_ref')
  })

  it('does not submit a fully selected agent draft from old dialog state in the same turn as a project switch', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') {
        return { data: [{ id: 'skill-a', name: 'Skill A', latest_version: '1.0.0' }] }
      }
      if (path === '/environments') return { data: [{ id: 'env-a', name: 'Env A' }] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: 'agent-created' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(getByText('secret-a')).toBeTruthy()
      expect(getByText('Env A')).toBeTruthy()
      expect(getByText('Skill A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.agents.create.namePlaceholder'), {
        target: { value: 'Project A Agent' },
      })
      fireEvent.input(getByPlaceholderText('managed.agents.create.descriptionPlaceholder'), {
        target: { value: 'Uses project A resources' },
      })
      fireEvent.input(getByPlaceholderText('managed.agents.create.systemPromptPlaceholder'), {
        target: { value: 'Answer using project A context.' },
      })
      fireEvent.click(getByText('Env A'))
      fireEvent.click(getByText('Skill A'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents', expect.anything())
  })

  it('ignores a create completion after the managed project changes', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const create = deferred<{ id: string }>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const onCreated = vi.fn()
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByPlaceholderText, getByText } = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={onCreated} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/secrets')
    })

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.agents.create.namePlaceholder'), {
        target: { value: 'Project A Agent' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      create.resolve({ id: 'agent-created-in-project-a' })
      await Promise.resolve()
    })

    expect(onCreated).not.toHaveBeenCalled()
  })

  it('ignores a create completion after the dialog unmounts', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const create = deferred<{ id: string }>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const onOpenChange = vi.fn()
    const onCreated = vi.fn()
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={onOpenChange} onCreated={onCreated} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/secrets')
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.agents.create.namePlaceholder'), {
        target: { value: 'Unmounted Agent' },
      })
    })

    await act(async () => {
      fireEvent.click(view.getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      create.resolve({ id: 'agent-created-after-unmount' })
      await Promise.resolve()
    })

    expect(onOpenChange).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  ApiError: class ApiError extends Error {
    status = 500
    code?: string
    detail?: string
  },
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/lib/managed/sse', () => ({
  useSessionStream: vi.fn(() => ({ events: [] })),
}))

vi.mock('@/hooks/managed/use-quickstart-chat', () => ({
  useQuickstartChat: vi.fn(),
}))

vi.mock('@/components/managed/session', () => ({
  EventDetail: () => null,
  EventFilter: () => null,
  EventList: () => <div>event-list</div>,
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

vi.mock('@/components/ui/select', () => {
  const React = require('react')
  const SelectContext = React.createContext({
    onValueChange: undefined as ((value: string) => void) | undefined,
  })

  return {
    Select: ({
      children,
      onValueChange,
      value,
    }: {
      children: ReactNode
      onValueChange?: (value: string) => void
      value?: string
    }) => (
      <SelectContext.Provider value={{ onValueChange }}>
        <div data-select-value={value}>{children}</div>
      </SelectContext.Provider>
    ),
    SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectItem: ({ children, value }: { children: ReactNode; value: string }) => {
      const context = React.useContext(SelectContext)
      return (
        <button type="button" onClick={() => context.onValueChange?.(value)}>
          {children}
        </button>
      )
    },
    SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectValue: () => null,
  }
})

vi.mock('js-yaml', () => ({
  default: {
    dump: (value: unknown) => JSON.stringify(value, null, 2),
  },
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.HTMLInputElement = dom.window.HTMLInputElement
globalThis.Event = dom.window.Event
globalThis.InputEvent = dom.window.InputEvent
globalThis.localStorage = dom.window.localStorage
globalThis.Element = dom.window.Element
Element.prototype.scrollIntoView = vi.fn()
globalThis.navigator.clipboard = {
  writeText: vi.fn(),
} as unknown as Clipboard

import { managedGet, managedPost } from '@/lib/api-client'
import { useQuickstartChat } from '@/hooks/managed/use-quickstart-chat'
import { useSessionStream } from '@/lib/managed/sse'
import { useProjectStore } from '@/stores/managed/project-store'

import QuickstartPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const useQuickstartChatMock = useQuickstartChat as unknown as ReturnType<typeof vi.fn>
const useSessionStreamMock = useSessionStream as unknown as ReturnType<typeof vi.fn>
const generateTestMessageMock = vi.fn()

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function renderQuickstart(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <QuickstartPage />
    </QueryClientProvider>,
  )
}

describe('QuickstartPage managed scope lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    useQuickstartChatMock.mockReset()
    generateTestMessageMock.mockReset()
    generateTestMessageMock.mockResolvedValue('test prompt')
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      completedSteps: new Set([1, 2, 3]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    useSessionStreamMock.mockClear()
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') return Promise.resolve({ data: [] })
      if (url === '/vaults') return Promise.resolve({ data: [] })
      if (url.startsWith('/sessions/')) return Promise.resolve({ id: 'session_a', status: 'idle' })
      return Promise.resolve({ data: [] })
    })
    managedPostMock.mockResolvedValue({ id: 'session_a' })
    useSessionStreamMock.mockReturnValue({ events: [] })
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      organizations: [],
      projects: [],
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

  it('does not activate a test session created after the managed project changes', async () => {
    const createSession = deferred<{ id: string }>()
    managedPostMock.mockReturnValueOnce(createSession.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env-a', name: 'Env A', archived_at: null },
      { id: 'env-b', name: 'Env B', archived_at: null },
    ])

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: /managed\.quickstart\.testRun/ }))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'agent_a' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await act(async () => {
      createSession.resolve({ id: 'session_from_project_a' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(useSessionStreamMock).not.toHaveBeenCalledWith('session_from_project_a', true)
    expect(managedGetMock).not.toHaveBeenCalledWith('/sessions/session_from_project_a')
  })

  it('does not start a test run from old quickstart UI in the same turn as a project switch', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env-a', name: 'Env A', archived_at: null },
    ])

    const view = renderQuickstart(queryClient)
    const testRunButton = await view.findByRole('button', {
      name: /managed\.quickstart\.testRun/,
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(testRunButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions', expect.anything())
  })

  it('does not start a final session from old quickstart UI in the same turn as a project switch', async () => {
    const createSession = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 4: 'env-a', 5: 'vault-a' },
      createdResourceIds: new Set(['agent_a']),
      completedSteps: new Set([1, 2, 3, 4, 5]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession,
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env-a', name: 'Env A', archived_at: null },
    ])
    queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
      data: [{ id: 'vault-a', name: 'Vault A', archived_at: null }],
    })

    const view = renderQuickstart(queryClient)
    const startButton = view.getByRole('button', { name: 'managed.quickstart.startSession' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(startButton)
      await Promise.resolve()
    })

    expect(createSession).not.toHaveBeenCalled()
  })

  it('keeps cURL copy feedback visible for two seconds after the latest copy', async () => {
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 3,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: { 3: 'curl -X POST /agents' },
      resourceIds: { 3: 'agent_a' },
      completedSteps: new Set([1, 2, 3]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const { getByText } = renderQuickstart(queryClient)
    const curl = getByText('curl -X POST /agents')
    const card = curl.closest('.rounded-xl')
    const copyButton = card?.querySelector('button') as HTMLButtonElement
    expect(copyButton).toBeTruthy()

    vi.useFakeTimers()

    await act(async () => {
      fireEvent.click(copyButton)
    })

    expect(copyButton.querySelector('.lucide-check')).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(1000)
      fireEvent.click(copyButton)
    })

    await act(async () => {
      vi.advanceTimersByTime(1500)
    })

    expect(copyButton.querySelector('.lucide-check')).toBeTruthy()
  })

  it('does not overwrite a manually typed session message when generated test text resolves later', async () => {
    const generatedMessage = deferred<string>()
    generateTestMessageMock.mockReturnValueOnce(generatedMessage.promise)
    managedPostMock.mockResolvedValueOnce({ id: 'session_a' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
      data: [
        { id: 'vault-a', name: 'Vault A', archived_at: null },
        { id: 'vault-b', name: 'Vault B', archived_at: null },
      ],
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: /managed\.quickstart\.testRun/ }))
      await Promise.resolve()
    })

    const input = (await view.findByPlaceholderText(
      'managed.quickstart.sendMessage',
    )) as HTMLInputElement

    await act(async () => {
      fireEvent.input(input, { target: { value: 'manual prompt' } })
    })

    expect(input.value).toBe('manual prompt')

    await act(async () => {
      generatedMessage.resolve('generated prompt')
      await generatedMessage.promise
      await Promise.resolve()
    })

    expect(input.value).toBe('manual prompt')
  })

  it('does not send a preview session message after the current session becomes running', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: /managed\.quickstart\.testRun/ }))
      await Promise.resolve()
    })

    const input = (await view.findByPlaceholderText(
      'managed.quickstart.sendMessage',
    )) as HTMLInputElement

    await act(async () => {
      fireEvent.input(input, { target: { value: 'message after stale idle' } })
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'org-a:project-a', 'session_a'], {
        id: 'session_a',
        status: 'running',
      })
      fireEvent.keyDown(input, { key: 'Enter', shiftKey: false })
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions/session_a/events', {
      events: [
        {
          type: 'user.message',
          content: [{ type: 'text', text: 'message after stale idle' }],
        },
      ],
    })
  })

  it('does not stop a preview session after the current session is no longer running', async () => {
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 6: 'session_a' },
      completedSteps: new Set([1, 2, 3, 6]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') return Promise.resolve({ data: [] })
      if (url === '/vaults') return Promise.resolve({ data: [] })
      if (url === '/sessions/session_a') {
        return Promise.resolve({ id: 'session_a', status: 'running', archived_at: null })
      }
      return Promise.resolve({ data: [] })
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await waitFor(() => {
      expect(view.getByRole('button', { name: 'managed.quickstart.stopSession' })).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['session', 'org-a:project-a', 'session_a'], {
        id: 'session_a',
        status: 'idle',
        archived_at: null,
      })
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.stopSession' }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions/session_a/stop', {})
  })

  it('does not create a test session with an environment that is no longer active', async () => {
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') {
        return Promise.resolve({
          data: [
            { id: 'env-a', name: 'Env A', archived_at: null },
            { id: 'env-b', name: 'Env B', archived_at: null },
          ],
        })
      }
      if (url === '/vaults') return Promise.resolve({ data: [] })
      if (url.startsWith('/sessions/')) return Promise.resolve({ id: 'session_a', status: 'idle' })
      return Promise.resolve({ data: [] })
    })
    managedPostMock.mockResolvedValueOnce({ id: 'session_a' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByText('managed.quickstart.preview'))
    })

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Env A' }))
    })

    await act(async () => {
      queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
        { id: 'env-b', name: 'Env B', archived_at: null },
      ])
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.queryByRole('button', { name: 'Env A' })).toBeNull()
      expect(view.getByRole('button', { name: 'Env B' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getAllByRole('button', { name: /managed\.quickstart\.testRun/ })[0])
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'agent_a' })
    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions', {
      agent: 'agent_a',
      environment_id: 'env-a',
    })
  })

  it('does not create a test session with an environment that leaves the active list in the same turn', async () => {
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') {
        return Promise.resolve({
          data: [
            { id: 'env-a', name: 'Env A', archived_at: null },
            { id: 'env-b', name: 'Env B', archived_at: null },
          ],
        })
      }
      if (url === '/vaults') return Promise.resolve({ data: [] })
      if (url.startsWith('/sessions/')) return Promise.resolve({ id: 'session_a', status: 'idle' })
      return Promise.resolve({ data: [] })
    })
    managedPostMock.mockResolvedValueOnce({ id: 'session_a' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByText('managed.quickstart.preview'))
    })

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Env A' }))
    })

    await act(async () => {
      queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
        { id: 'env-b', name: 'Env B', archived_at: null },
      ])
      fireEvent.click(view.getAllByRole('button', { name: /managed\.quickstart\.testRun/ })[0])
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'agent_a' })
    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions', {
      agent: 'agent_a',
      environment_id: 'env-a',
    })
  })

  it('creates a test session with a quickstart-created environment even when the active list cache predates creation', async () => {
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 4: 'env_created' },
      createdResourceIds: new Set(['env_created']),
      completedSteps: new Set([1, 2, 3, 4]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') return Promise.resolve({ data: [] })
      if (url === '/vaults') return Promise.resolve({ data: [] })
      if (url.startsWith('/sessions/')) return Promise.resolve({ id: 'session_a', status: 'idle' })
      return Promise.resolve({ data: [] })
    })
    managedPostMock.mockResolvedValueOnce({ id: 'session_a' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [])

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByText('managed.quickstart.preview'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.container.querySelector('[data-select-value="env_created"]')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getAllByRole('button', { name: /managed\.quickstart\.testRun/ })[0])
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/sessions', {
      agent: 'agent_a',
      environment_id: 'created',
    })
  })

  it('does not create a test session with a quickstart-created environment that is now archived', async () => {
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 4: 'env_created' },
      createdResourceIds: new Set(['env_created']),
      completedSteps: new Set([1, 2, 3, 4]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') {
        return Promise.resolve({
          data: [
            {
              id: 'env_created',
              name: 'Created Env',
              archived_at: '2026-07-10T00:00:00Z',
            },
          ],
        })
      }
      if (url === '/vaults') return Promise.resolve({ data: [] })
      if (url.startsWith('/sessions/')) return Promise.resolve({ id: 'session_a', status: 'idle' })
      return Promise.resolve({ data: [] })
    })
    managedPostMock.mockResolvedValueOnce({ id: 'session_a' })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env_created', name: 'Created Env', archived_at: '2026-07-10T00:00:00Z' },
    ])

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByText('managed.quickstart.preview'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.container.querySelector('[data-select-value="env_created"]')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getAllByRole('button', { name: /managed\.quickstart\.testRun/ })[0])
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith('/sessions', { agent: 'agent_a' })
    expect(managedPostMock).not.toHaveBeenCalledWith('/sessions', {
      agent: 'agent_a',
      environment_id: 'created',
    })
  })

  it('starts a session with quickstart-created resources even when active list caches predate creation', async () => {
    const createSession = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 4: 'env_created', 5: 'vault_created' },
      createdResourceIds: new Set(['agent_a', 'env_created', 'vault_created']),
      completedSteps: new Set([1, 2, 3, 4, 5]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession,
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [])
    queryClient.setQueryData(['vaults-active', 'org-a:project-a'], { data: [] })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.startSession' }))
      await Promise.resolve()
    })

    expect(createSession).toHaveBeenCalledWith({
      environmentId: 'env_created',
      vaultId: 'vault_created',
    })
  })

  it('does not start a session with existing resources that leave the current active lists', async () => {
    const createSession = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 4: 'env-a', 5: 'vault-a' },
      createdResourceIds: new Set(['agent_a']),
      completedSteps: new Set([1, 2, 3, 4, 5]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession,
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env-b', name: 'Env B', archived_at: null },
    ])
    queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
      data: [{ id: 'vault-b', name: 'Vault B', archived_at: null }],
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.startSession' }))
      await Promise.resolve()
    })

    expect(createSession).toHaveBeenCalledWith({
      environmentId: null,
      vaultId: null,
    })
  })

  it('does not start a session with quickstart-created resources that are now archived', async () => {
    const createSession = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a', 4: 'env_created', 5: 'vault_created' },
      createdResourceIds: new Set(['agent_a', 'env_created', 'vault_created']),
      completedSteps: new Set([1, 2, 3, 4, 5]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession,
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env_created', name: 'Created Env', archived_at: '2026-07-10T00:00:00Z' },
    ])
    queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
      data: [
        {
          id: 'vault_created',
          name: 'Created Vault',
          archived_at: '2026-07-10T00:00:00Z',
        },
      ],
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.startSession' }))
      await Promise.resolve()
    })

    expect(createSession).toHaveBeenCalledWith({
      environmentId: null,
      vaultId: null,
    })
  })

  it('does not start a session after the quickstart-created agent becomes archived', async () => {
    const createSession = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      createdResourceIds: new Set(['agent_a']),
      completedSteps: new Set([1, 2, 3, 4, 5]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession,
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['agent', 'org-a:project-a', 'agent_a'], {
      id: 'agent_a',
      name: 'Agent A',
      model: { id: 'claude-sonnet-4-5' },
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
      archived_at: '2026-07-10T00:01:00Z',
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.startSession' }))
      await Promise.resolve()
    })

    expect(createSession).not.toHaveBeenCalled()
  })

  it('starts a session with a quickstart-created agent when agent detail has not refreshed yet', async () => {
    const createSession = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 6,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      createdResourceIds: new Set(['agent_a']),
      completedSteps: new Set([1, 2, 3, 4, 5]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession,
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.startSession' }))
      await Promise.resolve()
    })

    expect(createSession).toHaveBeenCalledWith({
      environmentId: null,
      vaultId: null,
    })
  })

  it('does not enter environment confirmation for an option removed in the same turn', async () => {
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 4,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      completedSteps: new Set([1, 2, 3]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') {
        return Promise.resolve({
          data: [
            { id: 'env-a', name: 'Env A', archived_at: null },
            { id: 'env-b', name: 'Env B', archived_at: null },
          ],
        })
      }
      if (url === '/vaults') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
      { id: 'env-a', name: 'Env A', archived_at: null },
      { id: 'env-b', name: 'Env B', archived_at: null },
    ])

    const view = renderQuickstart(queryClient)
    const envAButton = await view.findByRole('button', { name: /Env A/ })

    await act(async () => {
      queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
        { id: 'env-b', name: 'Env B', archived_at: null },
      ])
      fireEvent.click(envAButton)
      await Promise.resolve()
    })

    expect(view.queryByRole('button', { name: 'managed.quickstart.nextConfigureVault' })).toBeNull()
    expect(view.getByRole('button', { name: /Env B/ })).toBeTruthy()
  })

  it('does not enter vault confirmation for an option removed in the same turn', async () => {
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 5,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      completedSteps: new Set([1, 2, 3, 4]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep: vi.fn(),
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') return Promise.resolve({ data: [] })
      if (url === '/vaults') {
        return Promise.resolve({
          data: [
            { id: 'vault-a', name: 'Vault A', archived_at: null },
            { id: 'vault-b', name: 'Vault B', archived_at: null },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
      data: [
        { id: 'vault-a', name: 'Vault A', archived_at: null },
        { id: 'vault-b', name: 'Vault B', archived_at: null },
      ],
    })

    const view = renderQuickstart(queryClient)
    const vaultAButton = await view.findByRole('button', { name: /Vault A/ })

    await act(async () => {
      queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
        data: [{ id: 'vault-b', name: 'Vault B', archived_at: null }],
      })
      fireEvent.click(vaultAButton)
      await Promise.resolve()
    })

    expect(view.queryByRole('button', { name: 'managed.quickstart.nextStartSession' })).toBeNull()
    expect(view.getByRole('button', { name: /Vault B/ })).toBeTruthy()
  })

  it('does not select an existing environment after it leaves the active list before confirmation', async () => {
    const selectExistingEnvironment = vi.fn()
    const advanceStep = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 4,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      completedSteps: new Set([1, 2, 3]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep,
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment,
      createVault: vi.fn(),
      selectExistingVault: vi.fn(),
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') {
        return Promise.resolve({
          data: [
            { id: 'env-a', name: 'Env A', archived_at: null },
            { id: 'env-b', name: 'Env B', archived_at: null },
          ],
        })
      }
      if (url === '/vaults') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: /Env A/ }))
    })

    await waitFor(() => {
      expect(
        view.getByRole('button', { name: 'managed.quickstart.nextConfigureVault' }),
      ).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['environments-active', 'org-a:project-a'], [
        { id: 'env-b', name: 'Env B', archived_at: null },
      ])
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.nextConfigureVault' }))
      await Promise.resolve()
    })

    expect(selectExistingEnvironment).not.toHaveBeenCalledWith('env-a')
    expect(advanceStep).not.toHaveBeenCalled()
  })

  it('does not select an existing vault after it leaves the active list before confirmation', async () => {
    const selectExistingVault = vi.fn()
    const advanceStep = vi.fn()
    useQuickstartChatMock.mockReturnValue({
      messages: [{ id: 'assistant-1', role: 'assistant', content: 'ready' }],
      currentStep: 5,
      selectedEngine: 'claude',
      config: { agent: { name: 'Agent A', system: 'Help.' } },
      isStreaming: false,
      curls: {},
      resourceIds: { 3: 'agent_a' },
      completedSteps: new Set([1, 2, 3, 4]),
      pendingConfirmation: null,
      isCreating: false,
      sendMessage: vi.fn(),
      selectEngine: vi.fn(),
      selectAgentSecret: vi.fn(),
      advanceStep,
      confirmStep: vi.fn(),
      keepRefining: vi.fn(),
      createSession: vi.fn(),
      createEnvironment: vi.fn(),
      selectExistingEnvironment: vi.fn(),
      createVault: vi.fn(),
      selectExistingVault,
      goToStep: vi.fn(),
      sendAutoIntro: vi.fn(),
      generateTestMessage: generateTestMessageMock,
    })
    managedGetMock.mockImplementation((url: string) => {
      if (url === '/secrets') {
        return Promise.resolve({
          data: [
            {
              name: 'anthropic-prod',
              provider: 'anthropic',
              protocol: 'anthropic_messages',
              is_default: true,
              keys: ['ANTHROPIC_API_KEY'],
            },
          ],
        })
      }
      if (url === '/environments') return Promise.resolve({ data: [] })
      if (url === '/vaults') {
        return Promise.resolve({
          data: [
            { id: 'vault-a', name: 'Vault A', archived_at: null },
            { id: 'vault-b', name: 'Vault B', archived_at: null },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderQuickstart(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: /Vault A/ }))
    })

    await waitFor(() => {
      expect(view.getByRole('button', { name: 'managed.quickstart.nextStartSession' })).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['vaults-active', 'org-a:project-a'], {
        data: [{ id: 'vault-b', name: 'Vault B', archived_at: null }],
      })
      fireEvent.click(view.getByRole('button', { name: 'managed.quickstart.nextStartSession' }))
      await Promise.resolve()
    })

    expect(selectExistingVault).not.toHaveBeenCalledWith('vault-a')
    expect(advanceStep).not.toHaveBeenCalled()
  })
})

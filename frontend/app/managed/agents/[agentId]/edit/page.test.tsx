import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pushMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

vi.mock('@/lib/i18n', () => ({
  i18n: { language: 'en' },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/shared', () => ({
  FieldHelp: () => null,
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
  SkillVersionSelect: () => null,
}))

vi.mock('@/components/ui/alert', () => ({
  Alert: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDescription: ({ children }: { children: ReactNode }) => <div>{children}</div>,
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

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import type { Agent } from '@/types/managed'

import AgentEditPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function agent(overrides: Partial<Agent>): Agent {
  return {
    id: 'agent_default',
    name: 'Default Agent',
    model: { id: 'claude' },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
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

function renderPage(agentId: string, queryClient: QueryClient) {
  const params = {
    status: 'fulfilled',
    value: { agentId },
    then: () => undefined,
  } as unknown as Promise<{ agentId: string }>

  return (
    <QueryClientProvider client={queryClient}>
      <AgentEditPage params={params} />
    </QueryClientProvider>
  )
}

describe('AgentEditPage object lifecycle', () => {
  beforeEach(() => {
    pushMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedPostMock.mockImplementation(() => new Promise(() => {}))
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

  it('refetches the agent and selectable dependencies after the managed project changes', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({ id: 'agent-a', name: 'Agent A', version: 1 })
      }
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') {
        return { data: [{ id: 'skill-a', name: 'Skill A', latest_version: '1.0.0' }] }
      }
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

    const { getByDisplayValue } = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(getByDisplayValue('Agent A')).toBeTruthy()
      expect(managedGetMock).toHaveBeenCalledWith('/agents/agent-a', managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith('/secrets', managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith('/skills', managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith('/environments', managedOptions())
    })
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a')).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets')).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/skills')).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments')).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/agents/agent-a')).toHaveLength(
        2,
      )
      expect(managedGetMock).toHaveBeenCalledWith('/agents/agent-a', managedOptions('project-b'))
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/secrets')).toHaveLength(2)
      expect(managedGetMock).toHaveBeenCalledWith('/secrets', managedOptions('project-b'))
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/skills')).toHaveLength(2)
      expect(managedGetMock).toHaveBeenCalledWith('/skills', managedOptions('project-b'))
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments')).toHaveLength(2)
      expect(managedGetMock).toHaveBeenCalledWith('/environments', managedOptions('project-b'))
    })
  })

  it('does not carry optional form state from one agent into another agent save', async () => {
    const agentA = agent({
      id: 'agent-a',
      name: 'Agent A',
      version: 7,
      tools: [
        {
          type: 'agent_toolset_20260401',
          configs: [{ name: 'Bash', enabled: false }],
        },
      ],
      mcp_servers: [{ type: 'url', name: 'old-mcp', url: 'https://old.example/mcp' }],
      skills: [{ type: 'custom', skill_id: 'skill-a', version: '1.0.0' }],
      secret_ref: 'secret-a',
      environment_ref: 'env-a',
      env: { OLD_ENV: '1' },
    })
    const agentB = agent({
      id: 'agent-b',
      name: 'Agent B',
      version: 3,
      tools: undefined,
      mcp_servers: [],
      skills: [],
      secret_ref: null,
      environment_ref: null,
      env: {},
    })

    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') return agentA
      if (path === '/agents/agent-b') return agentB
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') {
        return { data: [{ id: 'skill-a', name: 'Skill A', latest_version: '1.0.0' }] }
      }
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

    const { getByDisplayValue, getByText, rerender } = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(getByDisplayValue('Agent A')).toBeTruthy()
    })

    await act(async () => {
      rerender(renderPage('agent-b', queryClient))
    })

    await waitFor(() => {
      expect(getByDisplayValue('Agent B')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getByText('managed.agents.saveChanges'))
    })

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledTimes(1)
    })
    expect(managedPostMock.mock.calls[0][0]).toBe('/agents/agent-b')
    const payload = managedPostMock.mock.calls[0][1] as Record<string, unknown>
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())
    expect(payload).toMatchObject({
      version: 3,
      mcp_servers: [],
      skills: [],
      env: {},
    })
    expect(payload.secret_ref).toBeUndefined()
    expect(payload.environment_ref).toBeUndefined()
    expect(payload.tools).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: 'agent_toolset_20260401',
          configs: expect.arrayContaining([
            expect.objectContaining({ name: 'Bash', enabled: true }),
          ]),
        }),
      ]),
    )
  })

  it('does not overwrite an unsaved agent draft when refreshed agent data arrives', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({ id: 'agent-a', name: 'Agent A', version: 1 })
      }
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(view.getByDisplayValue('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('Agent A'), {
        target: { value: 'Local Agent Draft' },
      })
    })

    await act(async () => {
      queryClient.setQueryData(
        ['agent', 'org-a:project-a', 'agent-a'],
        agent({ id: 'agent-a', name: 'Agent A Refresh', version: 1 }),
      )
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(queryClient.getQueryData(['agent', 'org-a:project-a', 'agent-a'])).toMatchObject({
        name: 'Agent A Refresh',
      })
    })
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(view.getByDisplayValue('Local Agent Draft')).toBeTruthy()
    expect(view.queryByDisplayValue('Agent A Refresh')).toBeNull()
  })

  it('does not save an old agent draft to a new project that has the same agent id', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({ id: 'agent-a', name: 'Agent A', version: 1 })
      }
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(view.getByDisplayValue('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.input(view.getByDisplayValue('Agent A'), {
        target: { value: 'Old Project Agent Draft' },
      })
    })

    queryClient.setQueryData(
      ['agent', 'org-a:project-b', 'agent-a'],
      agent({ id: 'agent-a', name: 'Project B Agent', version: 3 }),
    )
    const saveButton = view.getByText('managed.agents.saveChanges')

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not submit a secret after it leaves the current selectable secret list', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({
          id: 'agent-a',
          name: 'Agent A',
          version: 1,
          secret_ref: 'secret-a',
        })
      }
      if (path === '/secrets') return { data: [{ name: 'secret-a' }] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(view.getByDisplayValue('Agent A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['secrets', 'org-a:project-a'], { data: [] })
      fireEvent.click(view.getByText('managed.agents.saveChanges'))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledTimes(1)
    })
    expect(managedPostMock).toHaveBeenCalledWith(
      '/agents/agent-a',
      expect.anything(),
      managedOptions(),
    )
    expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('secret_ref')
  })

  it('does not save after the current agent detail becomes archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({ id: 'agent-a', name: 'Agent A', version: 1 })
      }
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(view.getByDisplayValue('Agent A')).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['agent', 'org-a:project-a', 'agent-a'],
        agent({
          id: 'agent-a',
          name: 'Agent A',
          version: 1,
          archived_at: '2026-01-02T00:00:00Z',
        }),
      )
      fireEvent.click(view.getByText('managed.agents.saveChanges'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not save after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({ id: 'agent-a', name: 'Agent A', version: 1 })
      }
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(view.getByDisplayValue('Agent A')).toBeTruthy()
    })

    const saveButton = view.getByText('managed.agents.saveChanges')

    await act(async () => {
      useProjectStore.setState({ currentProject: projectInfo('2026-01-02T00:00:00Z') })
      fireEvent.click(saveButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
    expect((view.getByText('managed.agents.saveChanges') as HTMLButtonElement).disabled).toBe(true)
  })

  it('does not navigate from a save completion after the page unmounts', async () => {
    const save = deferred<unknown>()
    managedPostMock.mockReturnValueOnce(save.promise)
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents/agent-a') {
        return agent({ id: 'agent-a', name: 'Agent A', version: 1 })
      }
      if (path === '/secrets') return { data: [] }
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = render(renderPage('agent-a', queryClient))

    await waitFor(() => {
      expect(view.getByDisplayValue('Agent A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('managed.agents.saveChanges'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/agents/agent-a',
      expect.anything(),
      managedOptions(),
    )

    view.unmount()

    await act(async () => {
      save.resolve({})
      await save.promise
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalledWith('/managed/agents/agent-a')
  })
})

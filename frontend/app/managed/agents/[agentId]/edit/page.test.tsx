import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, waitFor, type RenderResult } from '@testing-library/react'
import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const pushMock = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

let projectAllowsWrite = true
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => projectAllowsWrite,
  useCurrentProjectReadOnly: () => !projectAllowsWrite,
}))
vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({
    data: {
      version: 'test',
      protocols: [],
      credential_profiles: [],
      providers: [],
      engines: [
        {
          id: 'claude',
          display_name: 'Claude Code',
          enabled: true,
          supported_protocol_ids: ['anthropic_messages'],
          preferred_protocol_ids: ['anthropic_messages'],
        },
        {
          id: 'codex',
          display_name: 'Codex',
          enabled: true,
          supported_protocol_ids: ['openai_responses'],
          preferred_protocol_ids: ['openai_responses'],
        },
      ],
    },
    isSuccess: true,
    isLoading: false,
    isError: false,
  }),
}))

const persistedSecret = {
  id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
  name: 'anthropic-prod',
  kind: 'model' as const,
  provider: 'anthropic',
  protocol: 'anthropic_messages',
  model: 'claude-sonnet-4-5',
  compatible_engine_ids: ['claude'],
  is_default: true,
  data: { ANTHROPIC_API_KEY: 'secret' },
  created_at: '2026-08-07T00:00:00Z',
  updated_at: '2026-08-07T00:00:00Z',
}

const codexSecret = {
  ...persistedSecret,
  id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021',
  name: 'openai-prod',
  provider: 'openai',
  protocol: 'openai_responses',
  model: 'gpt-5',
  compatible_engine_ids: ['codex'],
}

vi.mock('@/hooks/managed/use-compatible-credentials', () => ({
  compatibleCredentialsQueryPrefix: (scopeKey: string, engineId: string) => [
    'compatible-credentials',
    scopeKey,
    engineId,
  ],
  compatibleCredentialsQueryKey: (scopeKey: string, engineId: string) => [
    'compatible-credentials',
    scopeKey,
    engineId,
  ],
  useCompatibleCredentials: ({ engineId }: { engineId: string }) => ({
    data: engineId === 'claude' ? [persistedSecret] : [codexSecret],
    isSuccess: true,
    isLoading: false,
    isError: false,
  }),
  useModelConnectionByName: ({ name, enabled }: { name: string; enabled: boolean }) => ({
    data: enabled && name === persistedSecret.id ? persistedSecret : null,
    isSuccess: true,
    isLoading: false,
    isError: false,
  }),
}))

vi.mock('@/components/managed/llm/compatible-credential-picker', () => ({
  CompatibleCredentialPicker: ({
    value,
    conflictCredential,
    conflictMessage,
    onChange,
  }: {
    value: string
    conflictCredential?: { name: string } | null
    conflictMessage?: string
    onChange: (value: string) => void
  }) => (
    <div>
      <span data-testid="secret-value">{value}</span>
      {conflictMessage ? <span>{conflictMessage}</span> : null}
      {conflictCredential ? <span>{conflictCredential.name}</span> : null}
      <button type="button" onClick={() => onChange(codexSecret.id)}>
        choose-openai
      </button>
    </div>
  ),
}))

vi.mock('@/components/managed/shared', () => ({
  AdvancedSection: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  FieldHelp: () => null,
  FormActionBar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  FormFieldLabel: ({ children }: { children: ReactNode }) => <label>{children}</label>,
  FormSectionCard: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  PageHeader: () => null,
  SkillVersionSelect: () => null,
  withEntityRouteGuard: (Component: (props: never) => ReactNode) => Component,
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

vi.mock('@/components/ui/input', () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
  }: {
    children: ReactNode
    onValueChange?: (value: string) => void
  }) => {
    const wireItems = (nodes: ReactNode): ReactNode =>
      Children.map(nodes, (child) => {
        if (!isValidElement(child)) return child
        return cloneElement(
          child as ReactElement<{ children?: ReactNode; onSelectValue?: (value: string) => void }>,
          {
            onSelectValue: onValueChange,
            children: wireItems((child.props as { children?: ReactNode }).children),
          },
        )
      })
    return <div>{wireItems(children)}</div>
  },
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
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

vi.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import AgentEditPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const AGENT_ID = 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122'

describe('AgentEditPage LLM compatibility', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    pushMock.mockReset()
    projectAllowsWrite = true
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: true,
        capability: 'write',
        archived_at: null,
      },
      organizations: [],
      projects: [],
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === `/agents/${AGENT_ID}`) {
        return {
          id: AGENT_ID,
          name: 'Existing Agent',
          description: null,
          model: { id: 'claude-sonnet-4-5' },
          engine_kind: 'claude',
          model_credential_id: persistedSecret.id,
          system: null,
          metadata: { system_prompt_mode: 'append' },
          env: {},
          tools: [],
          mcp_servers: [],
          skills: [],
          version: 1,
          created_at: '2026-08-07T00:00:00Z',
          updated_at: '2026-08-07T00:00:00Z',
        }
      }
      if (path === '/skills' || path === '/environments') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({})
  })

  it('keeps an incompatible persisted Model Connection visible and blocks save until resolved', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const params = Promise.resolve({ agentId: AGENT_ID })
    await params
    let view!: RenderResult
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <AgentEditPage params={params} />
        </QueryClientProvider>,
      )
    })

    await waitFor(() =>
      expect(view.getByTestId('secret-value').textContent).toBe(persistedSecret.id),
    )
    fireEvent.click(view.getByText('Codex'))

    await waitFor(() => {
      expect(view.getByText('managed.llm.incompatibleWithSelectedEngine')).toBeTruthy()
      expect(view.getAllByText('anthropic-prod').length).toBeGreaterThan(0)
      expect((view.getByText('managed.agents.saveChanges') as HTMLButtonElement).disabled).toBe(
        true,
      )
    })

    fireEvent.click(view.getByText('managed.llm.restoreOriginalEngine'))
    await waitFor(() => {
      expect(view.queryByText('managed.llm.incompatibleWithSelectedEngine')).toBeNull()
      expect((view.getByText('managed.agents.saveChanges') as HTMLButtonElement).disabled).toBe(
        false,
      )
    })

    fireEvent.click(view.getByText('Codex'))
    await waitFor(() => expect(view.getByText('managed.llm.reselectConfiguration')).toBeTruthy())
    fireEvent.click(view.getByText('managed.llm.reselectConfiguration'))
    fireEvent.click(view.getByText('managed.agents.saveChanges'))

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][1]).toMatchObject({
      engine_kind: 'codex',
      model_credential_id: null,
    })
  })

  it('ignores a save completion after the current project becomes read-only', async () => {
    let resolveSave!: (value: Record<string, unknown>) => void
    managedPostMock.mockImplementationOnce(
      () =>
        new Promise<Record<string, unknown>>((resolve) => {
          resolveSave = resolve
        }),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const params = Promise.resolve({ agentId: AGENT_ID })
    let view!: RenderResult
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <AgentEditPage params={params} />
        </QueryClientProvider>,
      )
    })

    fireEvent.click(await waitFor(() => view.getByText('managed.agents.saveChanges')))
    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())

    projectAllowsWrite = false
    resolveSave({ id: AGENT_ID })

    await act(async () => {})
    expect(pushMock).not.toHaveBeenCalled()
  })

  it('saves canonical remote MCP transport and explicit auth requirement', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const params = Promise.resolve({ agentId: AGENT_ID })
    await params
    let view!: RenderResult
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <AgentEditPage params={params} />
        </QueryClientProvider>,
      )
    })

    fireEvent.click(await waitFor(() => view.getByTitle('managed.agents.create.addMcpServer')))
    fireEvent.change(view.getByLabelText('managed.agents.create.mcpTransport'), {
      target: { value: 'sse' },
    })
    const authRequirement = view.getByLabelText(
      'managed.agents.create.mcpAuthRequirement',
    ) as HTMLSelectElement
    expect(authRequirement.disabled).toBe(true)
    expect(authRequirement.value).toBe('none')
    fireEvent.input(view.getByPlaceholderText('managed.agents.create.mcpNamePlaceholder'), {
      target: { value: 'events' },
    })
    fireEvent.input(view.getByPlaceholderText('managed.agents.create.mcpUrlPlaceholder'), {
      target: { value: ' https://events.example.com/sse ' },
    })
    fireEvent.click(view.getByText('managed.agents.create.add'))
    fireEvent.click(view.getByText('managed.agents.saveChanges'))

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][1]).toMatchObject({
      mcp_servers: [
        {
          type: 'sse',
          name: 'events',
          url: 'https://events.example.com/sse',
          auth_requirement: 'none',
        },
      ],
    })
  })

  it('saves local stdio MCP command, arguments, and environment without remote fields', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const params = Promise.resolve({ agentId: AGENT_ID })
    await params
    let view!: RenderResult
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <AgentEditPage params={params} />
        </QueryClientProvider>,
      )
    })

    fireEvent.click(await waitFor(() => view.getByTitle('managed.agents.create.addMcpServer')))
    fireEvent.change(view.getByLabelText('managed.agents.create.mcpTransport'), {
      target: { value: 'local_stdio' },
    })
    fireEvent.input(view.getByPlaceholderText('managed.agents.create.mcpNamePlaceholder'), {
      target: { value: 'local-tools' },
    })
    fireEvent.input(view.getByPlaceholderText('managed.agents.create.mcpCommandPlaceholder'), {
      target: { value: ' node ' },
    })
    fireEvent.input(view.getByPlaceholderText('managed.agents.create.mcpArgsPlaceholder'), {
      target: { value: 'server.js\n--safe' },
    })
    fireEvent.input(view.getByPlaceholderText('managed.agents.create.mcpEnvPlaceholder'), {
      target: { value: 'MODE=safe\nEMPTY=' },
    })
    fireEvent.click(view.getByText('managed.agents.create.add'))
    fireEvent.click(view.getByText('managed.agents.saveChanges'))

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][1]).toMatchObject({
      mcp_servers: [
        {
          type: 'local_stdio',
          name: 'local-tools',
          command: 'node',
          args: ['server.js', '--safe'],
          env: { MODE: 'safe', EMPTY: '' },
        },
      ],
    })
  })

  it('stores the updated agent before navigating to detail', async () => {
    managedPostMock.mockResolvedValueOnce({
      id: AGENT_ID,
      name: 'Existing Agent',
      engine_kind: 'claude',
      model: null,
      model_credential_id: persistedSecret.id,
      version: 2,
      created_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-27T00:00:00Z',
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const params = Promise.resolve({ agentId: AGENT_ID })
    let view!: RenderResult
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <AgentEditPage params={params} />
        </QueryClientProvider>,
      )
    })

    fireEvent.click(await waitFor(() => view.getByText('managed.agents.saveChanges')))

    await waitFor(() =>
      expect(queryClient.getQueryData(['agent', 'org-a:project-a', AGENT_ID])).toMatchObject({
        version: 2,
        updated_at: '2026-08-27T00:00:00Z',
      }),
    )
    expect(pushMock).toHaveBeenCalledWith(`/managed/agents/${AGENT_ID}`)
  })
})

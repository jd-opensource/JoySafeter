import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react'
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

vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({
    data: {
      version: 'test',
      protocols: [
        {
          id: 'anthropic_messages',
          display_name: 'Anthropic Messages API',
          description: 'Anthropic contract',
        },
      ],
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
        {
          id: 'native',
          display_name: 'Native',
          enabled: true,
          supported_protocol_ids: ['anthropic_messages'],
          preferred_protocol_ids: ['anthropic_messages'],
        },
        {
          id: 'pi',
          display_name: 'Pi',
          enabled: true,
          supported_protocol_ids: ['anthropic_messages'],
          preferred_protocol_ids: ['anthropic_messages'],
        },
      ],
      credential_profiles: [],
      providers: [
        {
          id: 'anthropic',
          display_name: 'Anthropic',
          enabled: true,
          protocol_bindings: [],
        },
      ],
    },
    isSuccess: true,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/components/managed/llm/model-connection-configurator', () => ({
  ModelConnectionConfigurator: ({
    onCreated,
    onCancel,
  }: {
    onCreated: (secret: Record<string, unknown>) => void
    onCancel?: () => void
  }) => (
    <div>
      <button
        type="button"
        onClick={() =>
          onCreated({
            id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f124',
            name: 'inline-secret',
            kind: 'model',
            provider: 'anthropic',
            protocol: 'anthropic_messages',
            model: 'claude-sonnet-4-5',
            compatible_engine_ids: ['claude'],
            is_default: false,
            data: { ANTHROPIC_API_KEY: 'secret' },
            created_at: '2026-08-07T00:00:00Z',
            updated_at: '2026-08-07T00:00:00Z',
          })
        }
      >
        complete-inline-secret
      </button>
      <button type="button" onClick={onCancel}>
        cancel-inline-secret
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
        return cloneElement(
          child as ReactElement<{ children?: ReactNode; onSelectValue?: (value: string) => void }>,
          {
            onSelectValue: onValueChange,
            children: wireItems((child.props as { children?: ReactNode }).children),
          },
        )
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
const SKILL_ID = 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120'
const ENVIRONMENT_ID = 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f121'
const CREATED_AGENT_ID = 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122'
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

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

function compatibleSecretsPath(engineId = 'claude') {
  return `/credentials?limit=100&kind=model&include_archived=false&compatible_engine=${engineId}`
}

function credentialIdForName(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) % 0xfff
  }
  const suffix = hash.toString(16).padStart(3, '0')
  return `cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f${suffix}`
}

function llmSecret(name: string, isDefault = true, compatibleEngineIds = ['claude']) {
  return {
    id: credentialIdForName(name),
    name,
    kind: 'model',
    provider: 'anthropic',
    protocol: 'anthropic_messages',
    model: 'claude-sonnet-4-5',
    compatible_engine_ids: compatibleEngineIds,
    is_default: isDefault,
    data: { ANTHROPIC_API_KEY: 'secret' },
    archived_at: null,
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  }
}

function secretPage(items: ReturnType<typeof llmSecret>[]) {
  return { data: items, has_more: false, last_id: items.at(-1)?.id ?? null }
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    capability: 'write',
    archived_at: archivedAt,
  }
}

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

  it('refetches selectable dependencies instead of reusing previous project data', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([llmSecret('secret-a')])
      if (path === '/skills')
        return { data: [{ id: SKILL_ID, name: 'Skill A', latest_version: '1.0.0' }] }
      if (path === '/environments') return { data: [{ id: ENVIRONMENT_ID, name: 'Env A' }] }
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
      expect(managedGetMock).toHaveBeenCalledWith(compatibleSecretsPath(), managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith('/skills', managedOptions())
      expect(managedGetMock).toHaveBeenCalledWith('/environments', managedOptions())
    })
    expect(
      managedGetMock.mock.calls.filter(([path]) => path === compatibleSecretsPath()),
    ).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/skills')).toHaveLength(1)
    expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments')).toHaveLength(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(
        managedGetMock.mock.calls.filter(([path]) => path === compatibleSecretsPath()),
      ).toHaveLength(2)
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/skills')).toHaveLength(2)
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments')).toHaveLength(2)
    })
  })

  it('does not submit a secret selected from the previous project after managed context data changes', async () => {
    let secretName = 'secret-a'
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) {
        return secretPage([llmSecret(secretName)])
      }
      if (path === '/skills') {
        return { data: [] }
      }
      if (path === '/environments') {
        return { data: [] }
      }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: CREATED_AGENT_ID })
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
      expect(managedGetMock).toHaveBeenCalledWith(compatibleSecretsPath(), managedOptions())
      expect(getByText('secret-a')).toBeTruthy()
    })

    secretName = 'secret-b'
    await act(async () => {
      clearNonSessionQueryData(queryClient, { refetchActive: true })
    })

    await waitFor(() => {
      const secretCalls = managedGetMock.mock.calls.filter(
        ([path]) => path === compatibleSecretsPath(),
      )
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
      expect((getByText('managed.agents.create.submit') as HTMLButtonElement).disabled).toBe(false)
    })

    await act(async () => {
      getByText('managed.agents.create.submit').click()
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())
    expect(managedPostMock.mock.calls[0][1]).toMatchObject({ name: 'Created Agent' })
    expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('model_credential_id')
  })

  it('does not submit a default secret after the user chooses no selection', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([llmSecret('secret-a')])
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: CREATED_AGENT_ID })
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
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())
    expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('model_credential_id')
  })

  it('does not submit a default secret after it leaves the current selectable secret list', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([llmSecret('secret-a')])
      if (path === '/skills') return { data: [] }
      if (path === '/environments') return { data: [] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: CREATED_AGENT_ID })
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
      expect((getByText('managed.agents.create.submit') as HTMLButtonElement).disabled).toBe(false)
    })

    await act(async () => {
      queryClient.setQueryData(['compatible-credentials', 'org-a:project-a', 'claude'], [])
      fireEvent.click(getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())
    expect(managedPostMock.mock.calls[0][1]).not.toHaveProperty('model_credential_id')
  })

  it('preserves a selected secret when the next engine also supports it', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath('claude')) {
        return secretPage([llmSecret('shared-secret', true, ['claude', 'codex'])])
      }
      if (path === compatibleSecretsPath('codex')) {
        return secretPage([llmSecret('shared-secret', true, ['claude', 'codex'])])
      }
      if (path === '/skills' || path === '/environments') return { data: [] }
      return { data: [] }
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(view.getByRole('radio', { name: /shared-secret/ }).getAttribute('aria-checked')).toBe(
        'true',
      )
    })

    fireEvent.click(view.getByText('Codex'))

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith(compatibleSecretsPath('codex'), managedOptions())
      expect(view.getByRole('radio', { name: /shared-secret/ }).getAttribute('aria-checked')).toBe(
        'true',
      )
    })
    expect(view.queryByText('managed.llm.previousConfigurationIncompatible')).toBeNull()
  })

  it('clears an incompatible secret without silently replacing it after an engine switch', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath('claude')) {
        return secretPage([llmSecret('claude-secret')])
      }
      if (path === compatibleSecretsPath('codex')) {
        return secretPage([llmSecret('codex-secret', true, ['codex'])])
      }
      if (path === '/skills' || path === '/environments') return { data: [] }
      return { data: [] }
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(view.getByRole('radio', { name: /claude-secret/ }).getAttribute('aria-checked')).toBe(
        'true',
      )
    })

    fireEvent.click(view.getByText('Codex'))

    await waitFor(() => {
      expect(view.getByText('managed.llm.previousConfigurationIncompatible')).toBeTruthy()
      expect(view.getByRole('radio', { name: /codex-secret/ }).getAttribute('aria-checked')).toBe(
        'false',
      )
      expect(
        view
          .getByRole('radio', { name: /managed.agents.edit.noSelection/ })
          .getAttribute('aria-checked'),
      ).toBe('true')
    })
  })

  it('preserves the agent draft and selects a newly created compatible secret', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([])
      if (path === '/skills' || path === '/environments') return { data: [] }
      return { data: [] }
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={queryClient}>
        <CreateAgentDialog open onOpenChange={() => {}} onCreated={() => {}} />
      </QueryClientProvider>,
    )

    fireEvent.input(view.getByPlaceholderText('managed.agents.create.namePlaceholder'), {
      target: { value: 'Draft Agent' },
    })
    await waitFor(() => expect(view.getByText('managed.llm.createConfiguration')).toBeTruthy())
    fireEvent.click(view.getByText('managed.llm.createConfiguration'))
    fireEvent.click(view.getByText('complete-inline-secret'))

    await waitFor(() => {
      expect(
        (view.getByPlaceholderText('managed.agents.create.namePlaceholder') as HTMLInputElement)
          .value,
      ).toBe('Draft Agent')
      expect(view.getByRole('radio', { name: /inline-secret/ }).getAttribute('aria-checked')).toBe(
        'true',
      )
    })
  })

  it('does not submit a fully selected agent draft from old dialog state in the same turn as a project switch', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([llmSecret('secret-a')])
      if (path === '/skills') {
        return { data: [{ id: SKILL_ID, name: 'Skill A', latest_version: '1.0.0' }] }
      }
      if (path === '/environments') return { data: [{ id: ENVIRONMENT_ID, name: 'Env A' }] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: CREATED_AGENT_ID })
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

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents', expect.anything(), managedOptions())
  })

  it('does not submit a fully selected agent draft after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([llmSecret('secret-a')])
      if (path === '/skills') {
        return { data: [{ id: SKILL_ID, name: 'Skill A', latest_version: '1.0.0' }] }
      }
      if (path === '/environments') return { data: [{ id: ENVIRONMENT_ID, name: 'Env A' }] }
      return { data: [] }
    })
    managedPostMock.mockResolvedValue({ id: CREATED_AGENT_ID })
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
        target: { value: 'Archived Project Agent' },
      })
      fireEvent.input(getByPlaceholderText('managed.agents.create.descriptionPlaceholder'), {
        target: { value: 'Uses resources from the archived project' },
      })
      fireEvent.input(getByPlaceholderText('managed.agents.create.systemPromptPlaceholder'), {
        target: { value: 'Answer using archived project context.' },
      })
      fireEvent.click(getByText('Env A'))
      fireEvent.click(getByText('Skill A'))
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(getByText('managed.agents.create.submit'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('/agents', expect.anything(), managedOptions())
  })

  it('ignores a create completion after the managed project changes', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([])
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
      expect(managedGetMock).toHaveBeenCalledWith(compatibleSecretsPath(), managedOptions())
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
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      create.resolve({ id: CREATED_AGENT_ID })
      await Promise.resolve()
    })

    expect(onCreated).not.toHaveBeenCalled()
  })

  it('ignores a create completion after the current project is archived', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([])
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
      expect(managedGetMock).toHaveBeenCalledWith(compatibleSecretsPath(), managedOptions())
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
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      create.resolve({ id: CREATED_AGENT_ID })
      await Promise.resolve()
    })

    expect(onCreated).not.toHaveBeenCalled()
  })

  it('ignores a create completion after the dialog unmounts', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === compatibleSecretsPath()) return secretPage([])
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
      expect(managedGetMock).toHaveBeenCalledWith(compatibleSecretsPath(), managedOptions())
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
    expect(managedPostMock.mock.calls[0][2]).toEqual(managedOptions())

    view.unmount()

    await act(async () => {
      create.resolve({ id: CREATED_AGENT_ID })
      await Promise.resolve()
    })

    expect(onOpenChange).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
  })
})

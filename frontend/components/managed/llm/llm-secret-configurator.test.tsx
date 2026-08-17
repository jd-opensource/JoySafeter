import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { LlmSecretConfigurator } from './llm-secret-configurator'

const catalog = {
  version: '1',
  protocols: [
    { id: 'anthropic_messages', display_name: 'Anthropic Messages', description: 'Anthropic' },
    { id: 'openai_responses', display_name: 'OpenAI Responses', description: 'Responses' },
    { id: 'chat_completions', display_name: 'Chat Completions', description: 'Chat' },
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
      id: 'native',
      display_name: 'Native',
      enabled: true,
      supported_protocol_ids: ['anthropic_messages', 'openai_responses', 'chat_completions'],
      preferred_protocol_ids: ['anthropic_messages'],
    },
  ],
  credential_profiles: [
    {
      id: 'anthropic_standard',
      fields: [
        {
          key: 'ANTHROPIC_API_KEY',
          label: 'API Key',
          type: 'secret',
          required: false,
          placeholder: null,
          help_text: null,
          options: [],
          advanced: false,
        },
        {
          key: 'ANTHROPIC_AUTH_TOKEN',
          label: 'Auth Token',
          type: 'secret',
          required: false,
          placeholder: null,
          help_text: null,
          options: [],
          advanced: true,
        },
        {
          key: 'ANTHROPIC_BASE_URL',
          label: 'Base URL',
          type: 'url',
          required: false,
          placeholder: null,
          help_text: null,
          options: [],
          advanced: false,
        },
      ],
      required_any_of: [['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN']],
      base_url_key: 'ANTHROPIC_BASE_URL',
      model_key: null,
    },
    {
      id: 'openai_bearer',
      fields: [
        {
          key: 'OPENAI_API_KEY',
          label: 'API Key',
          type: 'secret',
          required: true,
          placeholder: null,
          help_text: null,
          options: [],
          advanced: false,
        },
        {
          key: 'OPENAI_MODEL',
          label: 'Model',
          type: 'text',
          required: false,
          placeholder: null,
          help_text: null,
          options: [],
          advanced: false,
        },
      ],
      required_any_of: [],
      base_url_key: null,
      model_key: 'OPENAI_MODEL',
    },
  ],
  providers: [
    {
      id: 'anthropic',
      display_name: 'Anthropic',
      enabled: true,
      protocol_bindings: [
        {
          protocol_id: 'anthropic_messages',
          credential_profile_id: 'anthropic_standard',
          default_base_url: 'https://api.anthropic.com',
          model_suggestions: [],
        },
      ],
    },
    {
      id: 'openai',
      display_name: 'OpenAI',
      enabled: true,
      protocol_bindings: [
        {
          protocol_id: 'openai_responses',
          credential_profile_id: 'openai_bearer',
          default_base_url: 'https://api.openai.com/v1',
          model_suggestions: [],
        },
        {
          protocol_id: 'chat_completions',
          credential_profile_id: 'openai_bearer',
          default_base_url: 'https://api.openai.com/v1',
          model_suggestions: [],
        },
      ],
    },
  ],
}

vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({ data: catalog, isLoading: false, isError: false, refetch: vi.fn() }),
}))
vi.mock('@/lib/api-client', () => ({ managedPost: vi.fn() }))
vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: any) => (
    <select value={value} onChange={(event) => onValueChange(event.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: ({ children, ...props }: any) => <>{children}</>,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}))

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function setProject(id: string, archivedAt: string | null = null) {
  useProjectStore.setState({
    currentOrgId: 'org-a',
    currentProjectId: id,
    currentProject: {
      id,
      org_id: 'org-a',
      name: id,
      slug: id,
      is_default: true,
      archived_at: archivedAt,
      capability: 'write',
    },
    organizations: [],
    projects: [],
  })
}

function fillModelForm() {
  fireEvent.change(screen.getByLabelText('managed.llm.provider'), { target: { value: 'openai' } })
  fireEvent.change(screen.getByLabelText('managed.llm.protocol'), {
    target: { value: 'openai_responses' },
  })
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'sk-test' } })
  fireEvent.change(screen.getByPlaceholderText('managed.llm.configurationNamePlaceholder'), {
    target: { value: 'Primary model' },
  })
}

describe('LlmSecretConfigurator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setProject('project-a')
  })

  it('does not render an engine selector', () => {
    render(<LlmSecretConfigurator initialEngineId="claude" onCreated={vi.fn()} />)
    expect(screen.queryByLabelText('managed.llm.engine')).toBeNull()
  })

  it('auto-selects a unique provider and hides the protocol selector', () => {
    render(<LlmSecretConfigurator initialEngineId="claude" onCreated={vi.fn()} />)
    expect(screen.getByDisplayValue('Anthropic')).toBeTruthy()
    expect(screen.queryByLabelText('managed.llm.protocol')).toBeNull()
  })

  it('shows the protocol selector for a provider with multiple protocols', () => {
    render(<LlmSecretConfigurator initialEngineId="native" onCreated={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('managed.llm.provider'), { target: { value: 'openai' } })
    expect(screen.getByLabelText('managed.llm.protocol')).toBeTruthy()
  })

  it('marks a successful connection test stale after any value changes', async () => {
    managedPostMock.mockResolvedValueOnce({ ok: true, message: 'ok' })
    render(<LlmSecretConfigurator initialEngineId="native" onCreated={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('managed.llm.provider'), { target: { value: 'openai' } })
    fireEvent.change(screen.getByLabelText('managed.llm.protocol'), {
      target: { value: 'openai_responses' },
    })
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'sk-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'managed.llm.testConnection' }))

    await waitFor(() => expect(screen.getByText('managed.llm.connectionVerified')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-5' } })
    expect(screen.getByText('managed.llm.connectionTestStale')).toBeTruthy()
  })

  it('does not create a model connection after the project becomes archived', async () => {
    render(<LlmSecretConfigurator initialEngineId="native" onCreated={vi.fn()} />)
    fillModelForm()

    await act(async () => {
      setProject('project-a', '2026-08-13T01:00:00Z')
      fireEvent.click(screen.getByRole('button', { name: 'managed.llm.createConfiguration' }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('ignores a model create completion after the project changes', async () => {
    const create = deferred<unknown>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const onCreated = vi.fn()
    render(<LlmSecretConfigurator initialEngineId="native" onCreated={onCreated} />)
    fillModelForm()
    fireEvent.click(screen.getByRole('button', { name: 'managed.llm.createConfiguration' }))
    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())

    await act(async () => {
      setProject('project-b')
      create.resolve({
        id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f098',
        name: 'Primary model',
        kind: 'model',
        provider: 'openai',
        protocol: 'openai_responses',
        model: null,
        compatible_engine_ids: ['native'],
        is_default: false,
        data: { OPENAI_API_KEY: '********' },
        archived_at: null,
        created_at: '2026-08-13T00:00:00Z',
        updated_at: '2026-08-13T00:00:00Z',
      })
      await create.promise
    })

    expect(onCreated).not.toHaveBeenCalled()
  })

  it('renders a single key input and an auth-scheme selector for anthropic', () => {
    render(<LlmSecretConfigurator initialEngineId="claude" onCreated={vi.fn()} />)
    expect(screen.getByLabelText('API Key')).toBeTruthy()
    expect(screen.queryByLabelText('Auth Token')).toBeNull()
    expect(screen.getByLabelText('managed.llm.authScheme')).toBeTruthy()
  })

  it('previews Bearer when base url is a gateway host', () => {
    render(<LlmSecretConfigurator initialEngineId="claude" onCreated={vi.fn()} />)
    // Anchor on the resolved-preview line's full text. In the test env t returns the
    // key, so the preview shows the preview key while the <option> labels show the
    // separate scheme keys — no overlap.
    expect(
      screen.getByText(
        (_content, el) => el?.textContent === 'managed.llm.authSchemePreviewApiKey',
      ),
    ).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'http://ai-api.jdcloud.com/anthropic' },
    })
    expect(
      screen.getByText(
        (_content, el) => el?.textContent === 'managed.llm.authSchemePreviewBearer',
      ),
    ).toBeTruthy()
  })

  it('submits auth_scheme for anthropic credentials', async () => {
    const create = deferred<unknown>()
    managedPostMock.mockReturnValueOnce(create.promise)
    render(<LlmSecretConfigurator initialEngineId="claude" onCreated={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'k' } })
    fireEvent.change(screen.getByPlaceholderText('managed.llm.configurationNamePlaceholder'), {
      target: { value: 'Claude key' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'managed.llm.createConfiguration' }))
    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    const [, body] = managedPostMock.mock.calls[0]
    expect(body.auth_scheme).toBe('auto')
    expect(body.data.ANTHROPIC_API_KEY).toBe('k')
  })
})

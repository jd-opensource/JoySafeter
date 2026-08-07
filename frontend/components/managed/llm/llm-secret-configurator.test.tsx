import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedPost } from '@/lib/api-client'

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
      supported_protocol_ids: [
        'anthropic_messages',
        'openai_responses',
        'chat_completions',
      ],
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
      ],
      required_any_of: [['ANTHROPIC_API_KEY']],
      base_url_key: null,
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
vi.mock('@/lib/managed/request-scope', () => ({
  managedRequestOptions: () => ({}),
  useManagedRequestScope: () => ({ orgId: 'org-a', projectId: 'project-a', key: 'scope' }),
}))
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

describe('LlmSecretConfigurator', () => {
  beforeEach(() => vi.clearAllMocks())

  it('auto-selects a unique protocol and shows multiple protocols explicitly', () => {
    render(<LlmSecretConfigurator initialEngineId="claude" onCreated={vi.fn()} />)

    expect(screen.getByDisplayValue('Anthropic')).toBeTruthy()
    expect(screen.queryByLabelText('managed.llm.protocol')).toBeNull()

    fireEvent.change(screen.getByLabelText('managed.llm.engine'), { target: { value: 'native' } })
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

    await waitFor(() =>
      expect(screen.getByText('managed.llm.connectionVerified')).toBeTruthy(),
    )
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'gpt-5' } })
    expect(screen.getByText('managed.llm.connectionTestStale')).toBeTruthy()
  })
})

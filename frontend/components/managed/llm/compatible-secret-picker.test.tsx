import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CompatibleSecretPicker } from './compatible-secret-picker'

const pickerMocks = vi.hoisted(() => ({
  queryError: false,
  catalogError: false,
  secretRefetch: vi.fn(),
  catalogRefetch: vi.fn(),
}))

const options = [
  {
    id: 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
    name: 'openai-prod',
    kind: 'llm' as const,
    provider: 'openai',
    protocol: 'openai_responses',
    model: 'gpt-5',
    compatible_engine_ids: ['codex'],
    is_default: true,
    keys: ['OPENAI_API_KEY'],
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
  },
]

vi.mock('@/hooks/managed/use-compatible-secrets', () => ({
  useCompatibleSecrets: () => ({
    data: options,
    isLoading: false,
    isError: pickerMocks.queryError,
    error: null,
    refetch: pickerMocks.secretRefetch,
  }),
}))
vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({
    data: {
      engines: [],
      credential_profiles: [],
      providers: [
        { id: 'openai', display_name: 'OpenAI', enabled: true, protocol_bindings: [] },
        { id: 'anthropic', display_name: 'Anthropic', enabled: true, protocol_bindings: [] },
      ],
      protocols: [
        {
          id: 'openai_responses',
          display_name: 'OpenAI Responses',
          description: 'Responses',
        },
        {
          id: 'anthropic_messages',
          display_name: 'Anthropic Messages',
          description: 'Messages',
        },
      ],
    },
    isLoading: false,
    isError: pickerMocks.catalogError,
    refetch: pickerMocks.catalogRefetch,
  }),
}))
vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

describe('CompatibleSecretPicker', () => {
  beforeEach(() => {
    pickerMocks.queryError = false
    pickerMocks.catalogError = false
    pickerMocks.secretRefetch.mockReset()
    pickerMocks.catalogRefetch.mockReset()
  })

  it('renders only server-returned compatible metadata and supports inline creation', () => {
    const onChange = vi.fn()
    const onCreateRequested = vi.fn()
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value=""
        onChange={onChange}
        onCreateRequested={onCreateRequested}
      />,
    )

    expect(screen.getByText(/openai-prod/)).toBeTruthy()
    expect(screen.getByText(/OpenAI Responses/)).toBeTruthy()
    expect(screen.getByText(/gpt-5/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'managed.llm.createConfiguration' }))
    expect(onCreateRequested).toHaveBeenCalledOnce()
  })

  it('offers an explicit engine-default option when empty selection is allowed', () => {
    const onChange = vi.fn()
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value="openai-prod"
        allowNone
        onChange={onChange}
        onCreateRequested={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('radio', { name: /managed.agents.edit.noSelection/ }))
    expect(onChange).toHaveBeenCalledWith('')
  })

  it('describes empty selection without claiming a runtime default exists', () => {
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value=""
        allowNone
        onChange={() => {}}
        onCreateRequested={() => {}}
      />,
    )

    expect(screen.getByText('managed.llm.noConfigurationHint')).toBeTruthy()
    expect(screen.queryByText('managed.llm.useEngineDefaultHint')).toBeNull()
  })

  it('keeps incompatible persisted configuration metadata visible', () => {
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value="legacy-anthropic"
        onChange={() => {}}
        onCreateRequested={() => {}}
        conflictSecret={{
          ...options[0],
          name: 'legacy-anthropic',
          provider: 'anthropic',
          protocol: 'anthropic_messages',
          model: 'claude-sonnet-4-5',
        }}
        conflictMessage="managed.llm.incompatibleWithSelectedEngine"
      />,
    )

    expect(screen.getByText('legacy-anthropic')).toBeTruthy()
    expect(screen.getByText(/Anthropic · Anthropic Messages · claude-sonnet-4-5/)).toBeTruthy()
  })

  it('shows the persisted name while exact conflict metadata is still loading', () => {
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value="legacy-anthropic"
        onChange={() => {}}
        onCreateRequested={() => {}}
        conflictValue="legacy-anthropic"
        conflictMessage="managed.llm.incompatibleWithSelectedEngine"
      />,
    )

    expect(screen.getByText('managed.llm.incompatibleWithSelectedEngine')).toBeTruthy()
    expect(screen.getByText('legacy-anthropic')).toBeTruthy()
  })

  it('keeps removed catalog identities visible without crashing', () => {
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value="orphan-secret"
        onChange={() => {}}
        onCreateRequested={() => {}}
        conflictSecret={{
          ...options[0],
          name: 'orphan-secret',
          provider: 'removed-provider',
          protocol: 'removed-protocol',
        }}
        conflictMessage="managed.llm.incompatibleWithSelectedEngine"
      />,
    )

    expect(screen.getByText(/removed-provider · removed-protocol/)).toBeTruthy()
  })

  it('retries both the catalog and compatible configuration queries', () => {
    pickerMocks.queryError = true
    pickerMocks.catalogError = true
    render(
      <CompatibleSecretPicker
        engineId="codex"
        value=""
        onChange={() => {}}
        onCreateRequested={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }))
    expect(pickerMocks.secretRefetch).toHaveBeenCalledOnce()
    expect(pickerMocks.catalogRefetch).toHaveBeenCalledOnce()
  })
})

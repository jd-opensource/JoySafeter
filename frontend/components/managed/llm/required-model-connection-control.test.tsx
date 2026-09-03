import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Credential } from '@/types/managed'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

vi.mock('@/components/managed/llm/model-connection-selection-flow', () => ({
  ModelConnectionSelectionFlow: ({
    onSelect,
    onCreated,
  }: {
    onSelect: (value: string) => void
    onCreated: (credential: Credential) => void
  }) => (
    <div>
      <button type="button" onClick={() => onSelect(CREDENTIAL.id)}>
        select-existing
      </button>
      <button type="button" onClick={() => onCreated(CREDENTIAL)}>
        create-inline
      </button>
    </div>
  ),
}))

import { RequiredModelConnectionControl } from './required-model-connection-control'

const CREDENTIAL: Credential = {
  id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
  name: 'OpenAI authoring',
  kind: 'model',
  provider: 'openai',
  protocol: 'openai_responses',
  model: 'gpt-5.5',
  compatible_engine_ids: ['codex'],
  is_default: false,
  auth_scheme: null,
  archived_at: null,
  created_at: '2026-09-02T00:00:00Z',
  updated_at: '2026-09-02T00:00:00Z',
}

function renderControl(
  overrides: Partial<React.ComponentProps<typeof RequiredModelConnectionControl>> = {},
) {
  const props: React.ComponentProps<typeof RequiredModelConnectionControl> = {
    engineId: 'codex',
    value: '',
    credentials: [],
    loading: false,
    loadError: false,
    onChange: vi.fn(),
    onCreated: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
  return { props, ...render(<RequiredModelConnectionControl {...props} />) }
}

describe('RequiredModelConnectionControl', () => {
  it('turns the empty state into an inline create flow', () => {
    const { props } = renderControl()

    fireEvent.click(screen.getByRole('button', { name: 'managed.llm.createConfiguration' }))
    expect(screen.getByText('managed.skills.aiAuthor.modelConnection.dialogTitle')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'create-inline' }))
    expect(props.onCreated).toHaveBeenCalledWith(CREDENTIAL)
  })

  it('shows the selected connection and allows replacing it', () => {
    const { props } = renderControl({ value: CREDENTIAL.id, credentials: [CREDENTIAL] })

    expect(screen.getByText('OpenAI authoring')).toBeTruthy()
    expect(screen.getByText('openai · openai_responses · gpt-5.5')).toBeTruthy()
    fireEvent.click(
      screen.getByRole('button', { name: 'managed.skills.aiAuthor.modelConnection.change' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'select-existing' }))
    expect(props.onChange).toHaveBeenCalledWith(CREDENTIAL.id)
  })

  it('offers retry instead of presenting a false empty state', () => {
    const onRetry = vi.fn()
    renderControl({ loadError: true, onRetry })

    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
    expect(screen.queryByText('managed.skills.aiAuthor.modelConnection.required')).toBeNull()
  })
})

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/components/managed/llm/compatible-secret-picker', () => ({
  CompatibleSecretPicker: ({
    onChange,
    onCreateRequested,
  }: {
    onChange: (value: string) => void
    onCreateRequested: () => void
  }) => (
    <div>
      <button type="button" onClick={() => onChange('openai-prod')}>
        choose-secret
      </button>
      <button type="button" onClick={onCreateRequested}>
        create-secret
      </button>
    </div>
  ),
}))

vi.mock('@/components/managed/llm/llm-secret-configurator', () => ({
  LlmSecretConfigurator: ({
    initialEngineId,
    onCancel,
    onCreated,
  }: {
    initialEngineId: string
    onCancel: () => void
    onCreated: (secret: Record<string, unknown>) => void
  }) => (
    <div>
      <span>{initialEngineId}</span>
      <button type="button" onClick={onCancel}>
        cancel-create
      </button>
      <button
        type="button"
        onClick={() =>
          onCreated({
            id: 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
            name: 'inline-secret',
          })
        }
      >
        complete-create
      </button>
    </div>
  ),
}))

import { QuickstartLlmStep } from './quickstart-llm-step'

describe('QuickstartLlmStep', () => {
  it('returns from inline creation to secret selection without rewinding the wizard', () => {
    const onSelect = vi.fn()
    const onCreated = vi.fn()
    render(
      <QuickstartLlmStep engineId="codex" value="" onSelect={onSelect} onCreated={onCreated} />,
    )

    fireEvent.click(screen.getByText('choose-secret'))
    expect(onSelect).toHaveBeenCalledWith('openai-prod')

    fireEvent.click(screen.getByText('create-secret'))
    expect(screen.getByText('codex')).toBeTruthy()
    fireEvent.click(screen.getByText('cancel-create'))
    expect(screen.getByText('create-secret')).toBeTruthy()

    fireEvent.click(screen.getByText('create-secret'))
    fireEvent.click(screen.getByText('complete-create'))
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ name: 'inline-secret' }))
    expect(screen.getByText('create-secret')).toBeTruthy()
  })
})

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Agent, ModelConnectionSummary } from '@/types/managed'

import { AgentModelSummary } from './agent-model-summary'

const translations: Record<string, string> = {
  'managed.modelDisplay.connection': 'Model Connection',
  'managed.modelDisplay.defaultConnection': 'Default',
  'managed.modelDisplay.connectionUnavailable': 'Bound model connection unavailable',
  'managed.modelDisplay.connectionUnavailableHint': 'The bound model connection could not be loaded.',
  'managed.modelDisplay.unbound': 'No model connection',
  'managed.modelDisplay.unboundHint': 'The agent will not receive model credentials.',
}

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) =>
      (translations[key] || key).replace(/{{(\w+)}}/g, (_, name: string) => values?.[name] || ''),
  }),
}))

const modelConnection = (
  overrides: Partial<ModelConnectionSummary> = {},
): ModelConnectionSummary =>
  ({
    id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f002',
    name: 'GPT-5',
    provider: 'openai',
    protocol: 'chat_completions',
    model: 'GPT-5',
    is_default: true,
    archived_at: null,
    ...overrides,
  }) as ModelConnectionSummary

const agent = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001',
    name: 'Agent',
    engine_kind: 'native',
    model: null,
    version: 1,
    model_credential_id: modelConnection().id,
    model_connection: modelConnection(),
    created_at: '2026-08-19T00:00:00Z',
    updated_at: '2026-08-19T00:00:00Z',
    ...overrides,
  }) as Agent

describe('AgentModelSummary', () => {
  afterEach(() => cleanup())

  it('renders one model connection summary in detail mode', () => {
    render(<AgentModelSummary agent={agent()} detail />)

    expect(screen.getAllByText('GPT-5')).toHaveLength(1)
    expect(screen.getByText('Default')).toBeInTheDocument()
    expect(screen.getByText('openai · chat_completions')).toBeInTheDocument()
  })

  it('uses the connection name instead of the legacy agent model', () => {
    render(
      <AgentModelSummary
        agent={agent({
          model: { id: 'Legacy Model' },
          model_connection: modelConnection({ name: 'OpenAI Prod' }),
        })}
      />,
    )

    expect(screen.getByText('OpenAI Prod')).toBeInTheDocument()
    expect(screen.queryByText('Legacy Model')).not.toBeInTheDocument()
  })

  it('can hide compact metadata in dense selectors', () => {
    render(<AgentModelSummary agent={agent()} showMeta={false} />)

    expect(screen.getByText('GPT-5')).toBeInTheDocument()
    expect(screen.queryByText('openai · chat_completions')).not.toBeInTheDocument()
  })
})

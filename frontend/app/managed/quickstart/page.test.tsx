import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/lib/i18n/config'
import { useProjectStore } from '@/stores/managed/project-store'

const quickstartState = vi.hoisted(() => ({
  selectAgentSecret: vi.fn(),
}))

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))

vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({ data: {}, isLoading: false, isError: false, refetch: vi.fn() }),
}))

vi.mock('@/lib/managed/llm-catalog', () => ({ getEnabledEngines: () => [] }))

vi.mock('@/hooks/managed/use-compatible-secrets', () => ({
  compatibleSecretsQueryPrefix: () => ['compatible-secrets'],
  useCompatibleSecrets: () => ({
    data: [
      {
        id: 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
        name: 'model-prod',
        kind: 'llm',
        provider: 'openai',
        protocol: 'openai_responses',
        model: 'gpt-5',
        compatible_engine_ids: ['codex'],
        is_default: true,
        keys: ['OPENAI_API_KEY'],
        created_at: '2030-01-01T00:00:00Z',
        updated_at: '2030-01-01T00:00:00Z',
      },
    ],
    isSuccess: true,
  }),
}))

vi.mock('@/hooks/managed/use-quickstart-chat', () => ({
  useQuickstartChat: () => ({
    messages: [{ id: 'message-1', role: 'user', content: 'Create an agent' }],
    currentStep: 3,
    selectedEngine: 'codex',
    config: { agent: { name: 'Research Agent' } },
    isStreaming: false,
    curls: {},
    resourceIds: {},
    createdResourceIds: new Set<string>(),
    completedSteps: new Set([1, 2]),
    pendingConfirmation: null,
    isCreating: false,
    sendMessage: vi.fn(),
    applyTemplate: vi.fn(),
    selectEngine: vi.fn(),
    selectAgentSecret: quickstartState.selectAgentSecret,
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
    generateTestMessage: vi.fn().mockResolvedValue(''),
  }),
}))

vi.mock('@/lib/managed/sse', () => ({ useSessionStream: () => ({ events: [] }) }))

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>()
  return {
    ...actual,
    managedGet: vi.fn((path: string) =>
      Promise.resolve(path === '/vaults' ? { data: [] } : { data: [] }),
    ),
    managedPost: vi.fn(),
  }
})

import QuickstartPage from './page'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('Quickstart page Model Connection completion', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
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
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('renders the compact approved Model Connection badge after advancing to Agent creation', async () => {
    render(<QuickstartPage />, { wrapper })

    await waitFor(() =>
      expect(screen.getByText('Model Connection Selected: model-prod')).toBeInTheDocument(),
    )
    expect(
      screen.queryByText(
        'Model Connection selected. The Agent will use this connection for model, endpoint, and API key settings at runtime.',
      ),
    ).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('managed.quickstart.stepDesc.')
  })
})

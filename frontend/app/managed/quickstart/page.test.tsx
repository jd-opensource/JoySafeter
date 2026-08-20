import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/lib/i18n/config'
import { useProjectStore } from '@/stores/managed/project-store'
import { SESSION_ID } from '@/test-utils/entity-ids'

const quickstartState = vi.hoisted(() => ({
  messages: [{ id: 'message-1', role: 'user', content: 'Create an agent' }],
  currentStep: 3,
  selectedEngine: 'codex' as string | null,
  config: { agent: { name: 'Research Agent' } } as { agent?: Record<string, unknown> },
  generationState: {
    status: 'idle' as const,
    phase: 'understanding' as const,
    elapsedSeconds: 0,
    hasPartialConfig: false,
  },
  completedSteps: new Set([1, 2]),
  resourceIds: {} as Record<number, string>,
  sendMessage: vi.fn(),
  applyTemplate: vi.fn(),
  selectEngine: vi.fn(),
  selectAgentSecret: vi.fn(),
  reopenStep: vi.fn(),
  enabledEngines: [] as Array<{
    id: string
    display_name: string
    enabled: boolean
    supported_protocol_ids: string[]
    preferred_protocol_ids: string[]
  }>,
  compatibleSecrets: [
    {
      id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
      name: 'model-prod',
      kind: 'model',
      provider: 'openai',
      protocol: 'openai_responses',
      model: 'gpt-5',
      compatible_engine_ids: ['codex'],
      is_default: true,
      data: { OPENAI_API_KEY: 'sk-test' },
      archived_at: null,
      created_at: '2030-01-01T00:00:00Z',
      updated_at: '2030-01-01T00:00:00Z',
    },
  ] as Array<Record<string, unknown>>,
  activeModelConnections: [] as Array<Record<string, unknown>>,
  sessionEvents: [] as Array<{ id: string; type: string; data?: Record<string, unknown> }>,
  trialTasks: [] as Array<Record<string, unknown>>,
}))

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))

vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({ data: {}, isLoading: false, isError: false, refetch: vi.fn() }),
}))

vi.mock('@/lib/managed/llm-catalog', () => ({
  getEnabledEngines: () => quickstartState.enabledEngines,
  getProvider: (_catalog: unknown, providerId: string) => ({
    display_name: providerId === 'openai' ? 'OpenAI' : 'Anthropic',
  }),
  getProtocol: (_catalog: unknown, protocolId: string) => ({
    display_name: protocolId === 'openai_responses' ? 'OpenAI Responses' : 'Anthropic Messages',
  }),
}))

vi.mock('@/hooks/managed/use-compatible-secrets', () => ({
  compatibleSecretsQueryPrefix: () => ['compatible-secrets'],
  useActiveModelConnections: () => ({
    data: quickstartState.activeModelConnections,
    isSuccess: true,
  }),
  useCompatibleSecrets: () => ({
    data: quickstartState.compatibleSecrets,
    isSuccess: true,
  }),
}))

vi.mock('@/hooks/managed/use-quickstart-chat', () => ({
  useQuickstartChat: () => ({
    messages: quickstartState.messages,
    currentStep: quickstartState.currentStep,
    selectedEngine: quickstartState.selectedEngine,
    config: quickstartState.config,
    isStreaming: false,
    generationState: quickstartState.generationState,
    curls: {},
    resourceIds: quickstartState.resourceIds,
    createdResourceIds: new Set<string>(),
    completedSteps: quickstartState.completedSteps,
    pendingConfirmation: null,
    isCreating: false,
    sendMessage: quickstartState.sendMessage,
    cancelGeneration: vi.fn(),
    retryGeneration: vi.fn(),
    applyTemplate: quickstartState.applyTemplate,
    selectEngine: quickstartState.selectEngine,
    selectAgentSecret: quickstartState.selectAgentSecret,
    advanceStep: vi.fn(),
    confirmStep: vi.fn(),
    keepRefining: vi.fn(),
    createSession: vi.fn(),
    createEnvironment: vi.fn(),
    selectExistingEnvironment: vi.fn(),
    createVault: vi.fn(),
    selectExistingCredentialGroup: vi.fn(),
    goToStep: vi.fn(),
    reopenStep: quickstartState.reopenStep,
    sendAutoIntro: vi.fn(),
    generateTestMessage: vi.fn().mockResolvedValue(''),
  }),
}))

vi.mock('@/lib/managed/sse', () => ({
  useSessionStream: () => ({ events: quickstartState.sessionEvents }),
}))

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>()
  return {
    ...actual,
    managedGet: vi.fn((path: string) => {
      if (path.startsWith('/tasks?')) return Promise.resolve({ data: quickstartState.trialTasks })
      return Promise.resolve(path === '/credential-groups' ? { data: [] } : { data: [] })
    }),
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
    quickstartState.messages = [{ id: 'message-1', role: 'user', content: 'Create an agent' }]
    quickstartState.currentStep = 3
    quickstartState.selectedEngine = 'codex'
    quickstartState.config = { agent: { name: 'Research Agent' } }
    quickstartState.completedSteps = new Set([1, 2])
    quickstartState.resourceIds = {}
    quickstartState.sessionEvents = []
    quickstartState.trialTasks = []
    quickstartState.reopenStep.mockReset()
    quickstartState.enabledEngines = []
    quickstartState.compatibleSecrets = [
      {
        id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
        name: 'model-prod',
        kind: 'model',
        provider: 'openai',
        protocol: 'openai_responses',
        model: 'gpt-5',
        compatible_engine_ids: ['codex'],
        is_default: true,
        data: { OPENAI_API_KEY: 'sk-test' },
        archived_at: null,
        created_at: '2030-01-01T00:00:00Z',
        updated_at: '2030-01-01T00:00:00Z',
      },
    ]
    quickstartState.activeModelConnections = [...quickstartState.compatibleSecrets]
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

  it('keeps the landing input usable and asks users to confirm the recommended engine', async () => {
    quickstartState.messages = []
    quickstartState.currentStep = 1
    quickstartState.selectedEngine = null
    quickstartState.completedSteps = new Set()
    quickstartState.enabledEngines = [
      {
        id: 'native',
        display_name: 'Native',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
      {
        id: 'codex',
        display_name: 'Codex',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
      {
        id: 'pi',
        display_name: 'Pi',
        enabled: false,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
    ]

    render(<QuickstartPage />, { wrapper })

    const input = screen.getByPlaceholderText('Describe the secure agent you want to build...')
    expect(input).not.toBeDisabled()
    expect(document.body.textContent).not.toContain('Complete Step 1 above')

    fireEvent.change(input, {
      target: { value: 'Build a researcher that summarizes web pages' },
    })
    fireEvent.click(screen.getAllByLabelText('Send message...')[0])

    expect(quickstartState.selectEngine).not.toHaveBeenCalled()
    expect(quickstartState.sendMessage).not.toHaveBeenCalled()
    expect(screen.getByText('Choose a runtime before JoySafeter continues')).toBeTruthy()
    expect(screen.getByText('1 connection')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Pi Unavailable/ })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: /Use Codex Ready now/ }))

    expect(quickstartState.selectEngine).toHaveBeenCalledWith('codex')
    expect(quickstartState.sendMessage).toHaveBeenCalledWith(
      'Build a researcher that summarizes web pages',
      { engineKindOverride: 'codex' },
    )
  })

  it('keeps the landing composer visible while the desktop template catalog scrolls independently', () => {
    quickstartState.messages = []
    quickstartState.currentStep = 1
    quickstartState.selectedEngine = null
    quickstartState.completedSteps = new Set()

    render(<QuickstartPage />, { wrapper })

    const composer = screen.getByPlaceholderText('Describe the secure agent you want to build...')
    const goalPanel = composer.closest('section')
    const templatePanel = screen
      .getByRole('heading', { name: 'Browse Templates' })
      .closest('section')

    expect(goalPanel).toHaveClass('lg:min-h-0')
    expect(templatePanel).toHaveClass('lg:min-h-0', 'lg:overflow-y-auto')
    expect(goalPanel?.parentElement).toHaveClass('lg:h-[calc(100vh-160px)]', 'lg:min-h-0')
  })

  it('uses the professional Agent Blueprint as the default desktop review surface', () => {
    quickstartState.currentStep = 3
    quickstartState.config = {
      agent: {
        name: 'Release Reviewer',
        blueprint: {
          mission: 'Review release changes before deployment.',
          responsibilities: ['Find correctness and security risks'],
          workflow: ['Inspect the change', 'Report prioritized findings'],
          boundaries: ['Never deploy changes'],
          tool_plan: ['Read-only repository access'],
          escalation_conditions: ['Escalate exposed credentials'],
          output_contract: ['Severity, evidence, remediation'],
          success_criteria: ['Every finding includes evidence'],
          acceptance_test: {
            message: 'Review this authentication change.',
            checks: ['Ranks findings by severity'],
          },
        },
      },
    }

    render(<QuickstartPage />, { wrapper })

    expect(screen.getByRole('button', { name: 'Agent Blueprint' })).toBeInTheDocument()
    expect(screen.getByText('Mission')).toBeInTheDocument()
    expect(screen.getByText('Review release changes before deployment.')).toBeInTheDocument()
    expect(screen.queryByText('YAML')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }))

    expect(screen.getByText('YAML')).toBeInTheDocument()
    expect(screen.getByText('JSON')).toBeInTheDocument()
  })

  it('presents Understand, Design, Protect, and Prove instead of six resource chores', () => {
    render(<QuickstartPage />, { wrapper })

    const progress = screen.getByRole('navigation', { name: 'Quickstart workflow' })
    expect(within(progress).getByText('Understand')).toBeInTheDocument()
    expect(within(progress).getByText('Design')).toBeInTheDocument()
    expect(within(progress).getByText('Protect')).toBeInTheDocument()
    expect(within(progress).getByText('Prove')).toBeInTheDocument()
    expect(within(progress).queryByText('Secure Model Connection')).not.toBeInTheDocument()
    expect(within(progress).queryByText('Authorize External Tools')).not.toBeInTheDocument()
  })

  it('applies a template with a professional blueprint and declared launch recommendations', () => {
    quickstartState.messages = []
    quickstartState.currentStep = 1
    quickstartState.selectedEngine = null
    quickstartState.completedSteps = new Set()
    quickstartState.enabledEngines = [
      {
        id: 'native',
        display_name: 'Native',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
    ]

    render(<QuickstartPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: /Deep Researcher/ }))

    expect(quickstartState.applyTemplate).toHaveBeenCalledWith(
      expect.objectContaining({
        agent: expect.objectContaining({
          blueprint: expect.objectContaining({
            mission: expect.any(String),
            acceptance_test: expect.objectContaining({
              message: expect.any(String),
              checks: expect.any(Array),
            }),
          }),
          metadata: expect.objectContaining({
            quickstart_runtime_intent: 'web_research',
            quickstart_safety_posture: expect.stringContaining('limited'),
          }),
        }),
      }),
    )
    expect(
      screen.getAllByText(/Blueprint and launch recommendations included/).length,
    ).toBeGreaterThan(0)
  })

  it('recommends a ready runtime before a coding runtime that requires Model Connection setup', () => {
    quickstartState.messages = []
    quickstartState.currentStep = 1
    quickstartState.selectedEngine = null
    quickstartState.completedSteps = new Set()
    quickstartState.enabledEngines = [
      {
        id: 'native',
        display_name: 'Native',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
      {
        id: 'codex',
        display_name: 'Codex',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
    ]
    quickstartState.activeModelConnections = [
      {
        ...quickstartState.compatibleSecrets[0],
        compatible_engine_ids: ['native'],
      },
    ]

    render(<QuickstartPage />, { wrapper })

    const input = screen.getByPlaceholderText('Describe the secure agent you want to build...')
    fireEvent.change(input, { target: { value: 'Review this TypeScript repository for bugs' } })
    fireEvent.click(screen.getAllByLabelText('Send message...')[0])

    expect(screen.getByRole('button', { name: /Use Native/ })).toBeTruthy()
    expect(screen.getByText('Ready now')).toBeTruthy()
    expect(screen.getByText('Setup required')).toBeTruthy()
  })

  it('auto-continues with the preferred protocol default when multiple defaults exist', async () => {
    quickstartState.messages = [{ id: 'message-1', role: 'user', content: 'Create a researcher' }]
    quickstartState.currentStep = 2
    quickstartState.selectedEngine = 'native'
    quickstartState.completedSteps = new Set([1])
    quickstartState.enabledEngines = [
      {
        id: 'native',
        display_name: 'Native',
        enabled: true,
        supported_protocol_ids: ['openai_responses', 'anthropic_messages'],
        preferred_protocol_ids: ['openai_responses'],
      },
    ]
    quickstartState.compatibleSecrets = [
      {
        id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021',
        name: 'anthropic-default',
        kind: 'model',
        provider: 'anthropic',
        protocol: 'anthropic_messages',
        model: 'claude-opus-4.6',
        compatible_engine_ids: ['native'],
        is_default: true,
        data: {},
        archived_at: null,
        created_at: '2030-01-02T00:00:00Z',
        updated_at: '2030-01-02T00:00:00Z',
      },
      {
        id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f022',
        name: 'openai-default',
        kind: 'model',
        provider: 'openai',
        protocol: 'openai_responses',
        model: 'gpt-5',
        compatible_engine_ids: ['native'],
        is_default: true,
        data: {},
        archived_at: null,
        created_at: '2030-01-01T00:00:00Z',
        updated_at: '2030-01-01T00:00:00Z',
      },
    ]

    render(<QuickstartPage />, { wrapper })

    await waitFor(() =>
      expect(quickstartState.selectAgentSecret).toHaveBeenCalledWith(
        'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f022',
      ),
    )
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

  it('shows a JoySafeter safety plan before secure launch', async () => {
    quickstartState.currentStep = 6
    quickstartState.selectedEngine = 'codex'
    quickstartState.completedSteps = new Set([1, 2, 3, 4, 5])
    quickstartState.enabledEngines = [
      {
        id: 'codex',
        display_name: 'Codex',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
    ]
    quickstartState.resourceIds = {
      3: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030',
      4: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f031',
      5: 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f032',
    }

    render(<QuickstartPage />, { wrapper })

    expect(screen.getByText('JoySafeter Safety Plan')).toBeInTheDocument()
    expect(screen.getByText('Ready for secure launch')).toBeInTheDocument()
    expect(screen.getByText('Runtime engine')).toBeInTheDocument()
    expect(screen.getByText('Codex')).toBeInTheDocument()
    expect(screen.getByText('Secure Model Connection')).toBeInTheDocument()
    expect(screen.getByText('model-prod')).toBeInTheDocument()
    expect(screen.getByText('Controlled environment')).toBeInTheDocument()
    expect(screen.getByText('Enforced')).toBeInTheDocument()
    expect(screen.getByText('External tool credentials')).toBeInTheDocument()
    expect(screen.getAllByText('Ready').length).toBeGreaterThan(1)
    expect(screen.getByText('Audit trail')).toBeInTheDocument()
    expect(screen.getByText('Automatic')).toBeInTheDocument()
    const secureLaunch = screen.getByRole('button', { name: 'Secure Launch' })
    expect(secureLaunch.closest('[data-quickstart-launch-footer]')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Change Model Connection'))

    expect(quickstartState.reopenStep).toHaveBeenCalledWith(2)
  })

  it('surfaces hardening recommendations when optional controls are missing', async () => {
    quickstartState.currentStep = 6
    quickstartState.selectedEngine = 'codex'
    quickstartState.completedSteps = new Set([1, 2, 3, 4, 5])
    quickstartState.enabledEngines = [
      {
        id: 'codex',
        display_name: 'Codex',
        enabled: true,
        supported_protocol_ids: ['openai_responses'],
        preferred_protocol_ids: ['openai_responses'],
      },
    ]
    quickstartState.resourceIds = {
      3: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030',
    }

    render(<QuickstartPage />, { wrapper })

    expect(screen.getByText('Hardening recommended')).toBeInTheDocument()
    expect(screen.getByText('Recommended')).toBeInTheDocument()
    expect(screen.getByText('Not authorized')).toBeInTheDocument()
    expect(screen.getByText('No custom environment selected')).toBeInTheDocument()
    expect(screen.getByText('No external tools authorized')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Launch is allowed without a custom environment, but this session will run without custom egress controls. Add one to enforce a narrow allowlist.',
      ),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Configure' }))

    expect(quickstartState.reopenStep).toHaveBeenCalledWith(4)
  })

  it('prefills security environment allowlist from user intent', async () => {
    quickstartState.messages = [
      { id: 'message-1', role: 'user', content: 'Build a GitHub repo triage agent' },
    ]
    quickstartState.currentStep = 4
    quickstartState.selectedEngine = 'codex'
    quickstartState.completedSteps = new Set([1, 2, 3])

    render(<QuickstartPage />, { wrapper })

    fireEvent.click(screen.getByText('Create New Security Environment'))
    fireEvent.click(screen.getByText('Limited (Recommended)'))

    expect(screen.getByText('JoySafeter suggested allowlist')).toBeInTheDocument()
    expect(screen.getByText('github.com')).toBeInTheDocument()
    expect(screen.getByText('api.github.com')).toBeInTheDocument()
    expect(screen.getByDisplayValue('github.com, api.github.com')).toBeInTheDocument()
  })

  it('recommends external tool authorization when MCP servers are configured', async () => {
    quickstartState.currentStep = 5
    quickstartState.selectedEngine = 'codex'
    quickstartState.completedSteps = new Set([1, 2, 3, 4])
    quickstartState.config = {
      agent: {
        name: 'MCP Agent',
        mcp_servers: {
          github: { url: 'https://api.github.com/mcp' },
        },
      },
    }

    render(<QuickstartPage />, { wrapper })

    expect(screen.getByText('JoySafeter external tool recommendation')).toBeInTheDocument()
    expect(
      screen.getByText(
        'This Agent configuration includes MCP servers, so authorize only the credential group it needs.',
      ),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByText('Authorize New MCP Credential Group'))

    expect(screen.getByDisplayValue('https://api.github.com/mcp')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('MCP bearer token')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Authorize External Tools' })).toBeDisabled()
  })

  it('shows response evidence without claiming the acceptance test passed', async () => {
    quickstartState.currentStep = 6
    quickstartState.completedSteps = new Set([1, 2, 3, 4, 5, 6])
    quickstartState.resourceIds = {
      3: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030',
      6: SESSION_ID,
    }
    quickstartState.sessionEvents = [
      { id: 'event-1', type: 'user.message' },
      { id: 'event-2', type: 'agent.message' },
      { id: 'event-3', type: 'session.status_idle' },
    ]
    quickstartState.config = {
      agent: {
        name: 'Release Reviewer',
        blueprint: {
          mission: 'Review releases',
          acceptance_test: {
            message: 'Review this authentication change.',
            checks: ['Ranks findings by severity', 'Includes evidence'],
          },
        },
      },
    }

    render(<QuickstartPage />, { wrapper })

    expect(await screen.findByText('Response received — review the acceptance checks')).toBeTruthy()
    expect(screen.queryByText('Agent is working correctly!')).not.toBeInTheDocument()
    expect(screen.getByText('Acceptance evidence')).toBeInTheDocument()
    expect(screen.getByText('Review this authentication change.')).toBeInTheDocument()
    expect(screen.getByText('Ranks findings by severity')).toBeInTheDocument()
    expect(screen.getByText('Includes evidence')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Review transcript' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Review debug evidence' })).toBeInTheDocument()
  })

  it('shows access rejection separately from a generic runtime failure', async () => {
    quickstartState.currentStep = 6
    quickstartState.completedSteps = new Set([1, 2, 3, 4, 5, 6])
    quickstartState.resourceIds = {
      3: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030',
      6: SESSION_ID,
    }
    quickstartState.sessionEvents = [{ id: 'event-1', type: 'user.message' }]
    quickstartState.trialTasks = [
      {
        id: 'task_018f6f42-0a51-7cc4-98c8-4f6f0ca5f070',
        status: 'failed',
        created_at: '2026-08-20T00:00:00Z',
        started_at: '2026-08-20T00:00:01Z',
        completed_at: '2026-08-20T00:00:02Z',
        error: 'Permission denied by execution policy',
      },
    ]

    render(<QuickstartPage />, { wrapper })

    expect(await screen.findByText('Launch access was rejected by policy')).toBeInTheDocument()
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const hoisted = vi.hoisted(() => ({
  state: { triggers: [] as TriggerRecord[] },
}))

interface TriggerRecord {
  id: string
  name: string
  description: string | null
  type: 'cron' | 'webhook' | 'manual'
  agent_id: string
  enabled: boolean
  auto_disabled_at: string | null
  disabled_reason: string | null
  session_mode: string
  cron_expr: string | null
  timezone: string | null
  run_at: string | null
  secret_ref: string | null
  next_run_at: string | null
  last_fired_slot: string | null
  webhook_url: string | null
  created_at: string
}

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}))

vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'org-a', projectId: 'project-a', key: 'org-a:project-a' }),
  managedRequestOptions: () => ({ headers: {} }),
  managedScopeKey: (o: string | null, p: string | null) => `${o ?? ''}:${p ?? ''}`,
}))

vi.mock('@/lib/managed/triggers', () => ({
  useAgentTriggers: () => ({ data: hoisted.state.triggers, isLoading: false, isFetching: false, isError: false }),
  useToggleAgentTrigger: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRunTrigger: () => ({ mutateAsync: vi.fn().mockResolvedValue({ status: 'fired' }), isPending: false }),
  useDeleteAgentTrigger: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

// The create dialog pulls in heavy child components; stub it out — this test
// only exercises the list page's capability gating + rendering.
vi.mock('@/components/managed/triggers/create-trigger-dialog', () => ({
  CreateTriggerDialog: () => null,
}))

vi.mock('@/lib/utils/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { useProjectStore } from '@/stores/managed/project-store'

import TriggerListPage from './page'

function setProject(capability?: 'read' | 'write' | 'admin') {
  useProjectStore.setState({
    currentOrgId: 'org-a',
    currentProjectId: 'project-a',
    currentProject: {
      id: 'project-a',
      org_id: 'org-a',
      name: 'Project A',
      slug: 'project-a',
      is_default: true,
      archived_at: null,
      ...(capability ? { capability } : {}),
    },
    organizations: [],
    projects: [],
  })
}

function cronTrigger(): TriggerRecord {
  return {
    id: 'trig_1',
    name: 'Daily report',
    description: null,
    type: 'cron',
    agent_id: 'agt_1',
    enabled: true,
    auto_disabled_at: null,
    disabled_reason: null,
    session_mode: 'fresh',
    cron_expr: '0 9 * * *',
    timezone: 'UTC',
    run_at: null,
    secret_ref: null,
    next_run_at: null,
    last_fired_slot: null,
    webhook_url: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function completedOneOffTrigger(): TriggerRecord {
  return {
    ...cronTrigger(),
    id: 'trig_once_done',
    name: 'One-off import',
    cron_expr: null,
    run_at: '2026-01-02T00:00:00Z',
    next_run_at: null,
    last_fired_slot: '2026-01-02T00:00:00Z',
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <TriggerListPage />
    </QueryClientProvider>,
  )
}

describe('TriggerListPage capability gate', () => {
  beforeEach(() => {
    hoisted.state.triggers = [cronTrigger()]
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      currentProject: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('shows the New Trigger button for a write-capable project and renders the row', () => {
    setProject('write')
    const { getByText } = renderPage()
    expect(getByText('managed.triggers.new')).toBeTruthy()
    expect(getByText('Daily report')).toBeTruthy()
  })

  it('hides the New Trigger button for a read-only project', () => {
    setProject('read')
    const { queryByText } = renderPage()
    expect(queryByText('managed.triggers.new')).toBeNull()
    expect(queryByText('Daily report')).toBeTruthy()
  })

  it('labels completed one-off triggers distinctly from active recurring triggers', () => {
    hoisted.state.triggers = [completedOneOffTrigger()]
    setProject('write')
    const { getByText } = renderPage()
    expect(getByText('One-off import')).toBeTruthy()
    expect(getByText('common.completed')).toBeTruthy()
  })
})

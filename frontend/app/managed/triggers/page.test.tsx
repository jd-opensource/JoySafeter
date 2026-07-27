import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const hoisted = vi.hoisted(() => ({
  createMutate: vi.fn(),
  deleteMutate: vi.fn(),
  state: { triggers: [] as TriggerRecord[] },
}))

interface TriggerRecord {
  id: string
  name: string
  enabled: boolean
  session_mode: string
  webhook_url: string
  last_error: string | null
}

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: () => Promise.resolve([]),
}))

vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'org-a', projectId: 'project-a', key: 'org-a:project-a' }),
  managedRequestOptions: () => ({}),
}))

vi.mock('@/lib/managed/triggers', () => ({
  useAgentTriggers: () => ({ data: hoisted.state.triggers }),
  useCreateAgentTrigger: () => ({ mutateAsync: hoisted.createMutate, isPending: false }),
  useDeleteAgentTrigger: () => ({ mutate: hoisted.deleteMutate, isPending: false }),
}))

vi.mock('@/lib/utils/toast', () => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, disabled }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) => (
    <button disabled={disabled} onClick={onClick}>{children}</button>
  ),
}))
vi.mock('@/components/ui/input', () => ({ Input: () => <input /> }))
vi.mock('@/components/ui/label', () => ({ Label: ({ children }: { children: ReactNode }) => <label>{children}</label> }))
vi.mock('@/components/ui/textarea', () => ({ Textarea: () => <textarea /> }))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { useProjectStore } from '@/stores/managed/project-store'

import AgentTriggersPage from './page'

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

function trigger(): TriggerRecord {
  return {
    id: 'trg-1',
    name: 'Alert hook',
    enabled: true,
    session_mode: 'fresh',
    webhook_url: 'https://example.com/hook/trg-1',
    last_error: null,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentTriggersPage />
    </QueryClientProvider>,
  )
}

describe('AgentTriggersPage capability gate', () => {
  beforeEach(() => {
    hoisted.createMutate.mockReset().mockResolvedValue({})
    hoisted.deleteMutate.mockReset()
    hoisted.state.triggers = [trigger()]
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null, currentProject: null, organizations: [], projects: [] })
    localStorage.clear()
  })

  it('shows the New Trigger button for a write-capable project', () => {
    setProject('write')
    const { getByText } = renderPage()
    expect(getByText('managed.triggers.new')).toBeTruthy()
  })

  it('renders the trigger row and localizes its session mode', () => {
    setProject('write')
    const { getByText } = renderPage()
    expect(getByText('Alert hook')).toBeTruthy()
    // enabled label + session_mode both resolve to i18n keys (no raw code leaks)
    expect(getByText(/managed\.triggers\.enabled.*managed\.schedules\.sessionModeOption\.fresh/)).toBeTruthy()
  })

  it('hides New Trigger and delete controls for a read-only project', () => {
    setProject('read')
    const { queryByText } = renderPage()
    expect(queryByText('managed.triggers.new')).toBeNull()
    // the read-only viewer still sees the row + copy button, but no destructive control
    expect(queryByText('Alert hook')).toBeTruthy()
  })
})

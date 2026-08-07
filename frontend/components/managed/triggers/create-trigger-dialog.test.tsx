import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AgentTrigger } from '@/lib/managed/triggers'
import { AGENT_ID, MANUAL_TRIGGER_ID, OTHER_TRIGGER_ID, TRIGGER_ID } from '@/test-utils/entity-ids'

const mutateAsync = vi.fn()

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  currentProjectAllowsWrite: () => true,
}))

vi.mock('@/hooks/managed/use-scoped-actions', () => ({
  useScopedActions: () => ({
    scope: { orgId: 'org-a', projectId: 'project-a', key: 'org-a:project-a' },
    beginAction: () => ({
      scope: { orgId: 'org-a', projectId: 'project-a', key: 'org-a:project-a' },
    }),
    isCurrentAction: () => true,
    scopeIsActive: () => true,
    bumpRun: vi.fn(),
  }),
}))

vi.mock('@/lib/managed/request-scope', () => ({
  hasManagedRequestScope: () => true,
  managedRequestOptions: () => ({ headers: {} }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(async (path: string) => {
    if (path.startsWith('/agents/')) return []
    if (path.startsWith('/agents'))
      return [
        {
          id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001',
          name: 'Agent 1',
          archived_at: null,
        },
      ]
    if (path.startsWith('/environments')) return []
    return []
  }),
}))

vi.mock('@/lib/managed/triggers', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/managed/triggers')>('@/lib/managed/triggers')
  return {
    ...actual,
    useCreateAgentTrigger: () => ({ mutateAsync, isPending: false }),
    useUpdateAgentTrigger: () => ({ mutateAsync, isPending: false }),
  }
})

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { CreateTriggerDialog } from './create-trigger-dialog'

function completedOneOffTrigger(): AgentTrigger {
  return {
    id: TRIGGER_ID,
    name: 'Completed once',
    description: null,
    type: 'cron',
    agent_id: AGENT_ID,
    prompt_template: 'run once',
    environment_ref: null,
    enabled: true,
    session_mode: 'fresh',
    pinned_session_id: null,
    reusable_session_id: null,
    session_key: null,
    filter: {},
    timeout_sec: 7200,
    max_retries: 2,
    cron_expr: null,
    timezone: 'UTC',
    run_at: '2000-01-01T00:00:00Z',
    concurrency_policy: 'allow',
    next_run_at: null,
    last_fired_slot: '2000-01-01T00:00:00Z',
    secret_ref: null,
    secret_key: null,
    config: {},
    project_id: 'project-a',
    webhook_url: null,
    last_attempt_at: null,
    last_success_at: null,
    last_error: null,
    consecutive_failures: 0,
    auto_disabled_at: null,
    disabled_reason: null,
    last_task_id: null,
    last_session_id: null,
    last_payload: {},
    created_at: '2000-01-01T00:00:00Z',
    updated_at: '2000-01-01T00:00:00Z',
  }
}

function pendingOneOffTrigger(): AgentTrigger {
  return {
    ...completedOneOffTrigger(),
    id: OTHER_TRIGGER_ID,
    name: 'Pending once',
    run_at: '2030-01-01T00:01:00Z',
    next_run_at: '2030-01-01T00:01:00Z',
    last_fired_slot: null,
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

function manualTrigger(): AgentTrigger {
  return {
    ...completedOneOffTrigger(),
    id: MANUAL_TRIGGER_ID,
    name: 'Manual only',
    type: 'manual',
    prompt_template: 'run on demand',
    cron_expr: null,
    timezone: null,
    run_at: null,
    concurrency_policy: 'allow',
    next_run_at: null,
    last_fired_slot: null,
  }
}

function renderDialog(trigger: AgentTrigger, open = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <CreateTriggerDialog open={open} onOpenChange={vi.fn()} trigger={trigger} />
    </QueryClientProvider>,
  )
  return {
    ...view,
    rerenderDialog(nextOpen: boolean) {
      view.rerender(
        <QueryClientProvider client={queryClient}>
          <CreateTriggerDialog open={nextOpen} onOpenChange={vi.fn()} trigger={trigger} />
        </QueryClientProvider>,
      )
    },
  }
}

describe('CreateTriggerDialog edit mode', () => {
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('allows saving metadata on a completed one-off trigger without re-sending past run_at', async () => {
    const { getByDisplayValue, getByText } = renderDialog(completedOneOffTrigger())

    expect(getByDisplayValue('Completed once')).toBeTruthy()
    const saveButton = getByText('common.save').closest('button')
    expect(saveButton?.hasAttribute('disabled')).toBe(false)

    fireEvent.click(saveButton!)

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    const payload = mutateAsync.mock.calls[0][0]
    expect(payload.id).toBe(TRIGGER_ID)
    expect('run_at' in payload.body).toBe(false)
    expect('cron_expr' in payload.body).toBe(false)
  })

  it('expires a pending one-off run_at while the dialog remains open', () => {
    vi.useFakeTimers({ now: new Date('2030-01-01T00:00:00Z') })
    const { getByDisplayValue, getByText } = renderDialog(pendingOneOffTrigger())

    expect(getByDisplayValue('Pending once')).toBeTruthy()
    const saveButton = getByText('common.save').closest('button')
    expect(saveButton?.hasAttribute('disabled')).toBe(false)

    act(() => {
      vi.advanceTimersByTime(90_000)
    })

    expect(saveButton?.hasAttribute('disabled')).toBe(true)
  })

  it('does not reopen with a stale future verdict after time passes while closed', () => {
    vi.useFakeTimers({ now: new Date('2030-01-01T00:00:00Z') })
    const view = renderDialog(pendingOneOffTrigger(), false)

    act(() => {
      vi.advanceTimersByTime(90_000)
    })
    view.rerenderDialog(true)

    const saveButton = view.getByText('common.save').closest('button')
    expect(saveButton?.hasAttribute('disabled')).toBe(true)
  })

  it('edits a manual trigger without leaking cron-only fields', async () => {
    const { getByDisplayValue, getByText, queryByText } = renderDialog(manualTrigger())

    expect(getByDisplayValue('Manual only')).toBeTruthy()
    expect(getByText('managed.triggers.typeOption.manual')).toBeTruthy()
    expect(getByText('{{ trigger.fired_at }}')).toBeTruthy()
    expect(getByText('{{ trigger.source_type }}')).toBeTruthy()
    expect(queryByText('{{ body }}')).toBeNull()
    const saveButton = getByText('common.save').closest('button')
    expect(saveButton?.hasAttribute('disabled')).toBe(false)

    fireEvent.click(saveButton!)

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    const payload = mutateAsync.mock.calls[0][0]
    expect(payload.id).toBe(MANUAL_TRIGGER_ID)
    expect(payload.body).not.toHaveProperty('cron_expr')
    expect(payload.body).not.toHaveProperty('run_at')
    expect(payload.body).not.toHaveProperty('timezone')
    expect(payload.body).not.toHaveProperty('concurrency_policy')
    expect(payload.body).not.toHaveProperty('secret_ref')
    expect(payload.body).not.toHaveProperty('auth_methods')
  })
})

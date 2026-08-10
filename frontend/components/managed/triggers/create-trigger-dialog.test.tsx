import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { act, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import type { AgentTrigger } from '@/lib/managed/triggers'
import { AGENT_ID, MANUAL_TRIGGER_ID, OTHER_TRIGGER_ID, TRIGGER_ID } from '@/test-utils/entity-ids'

const mutateAsync = vi.fn()
const secretParserState = vi.hoisted(() => ({ bypass: false }))

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
  useManagedRequestScope: () => ({
    orgId: 'org-a',
    projectId: 'project-a',
    key: 'org-a:project-a',
  }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
}))

vi.mock('@/lib/managed/secret-response-parsers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/managed/secret-response-parsers')>()
  return {
    ...actual,
    parseSecretListResponse: (response: unknown[]) =>
      secretParserState.bypass ? response : actual.parseSecretListResponse(response),
  }
})

vi.mock('@/components/ui/select', async () => {
  const React = await import('react')
  const SelectContext = React.createContext<(value: string) => void>(() => undefined)
  return {
    Select: ({
      children,
      value,
      onValueChange,
    }: {
      children: ReactNode
      value?: string
      onValueChange?: (value: string) => void
    }) => (
      <SelectContext.Provider value={onValueChange ?? (() => undefined)}>
        <div data-testid={value ? `select-${value}` : undefined}>{children}</div>
      </SelectContext.Provider>
    ),
    SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectItem: ({ children, value }: { children: ReactNode; value: string }) => {
      const onValueChange = React.useContext(SelectContext)
      if (!value.trim()) throw new Error('Radix SelectItem values must not be blank')
      return (
        <button type="button" data-select-value={value} onClick={() => onValueChange(value)}>
          {children}
        </button>
      )
    },
    SelectLabel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectTrigger: ({ children, ...props }: { children: ReactNode; 'aria-label'?: string }) => (
      <div {...props}>{children}</div>
    ),
    SelectValue: () => null,
  }
})

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

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const SERVICE_CREDENTIAL_ID = 'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'

function mockManagedApi({
  keys = ['WEBHOOK_SECRET', 'ALT_TOKEN'],
  secretError,
}: {
  keys?: string[]
  secretError?: Error
} = {}) {
  managedGetMock.mockImplementation(async (path: string) => {
    if (path.startsWith('/secrets?')) {
      if (secretError) throw secretError
      return {
        data: [
          {
            id: SERVICE_CREDENTIAL_ID,
            name: 'hook-prod',
            kind: 'generic',
            provider: null,
            protocol: null,
            model: null,
            compatible_engine_ids: [],
            is_default: false,
            keys,
            created_at: '2030-01-01T00:00:00Z',
            updated_at: '2030-01-01T00:00:00Z',
          },
        ],
        has_more: false,
        last_id: SERVICE_CREDENTIAL_ID,
      }
    }
    if (path.startsWith('/agents/')) return []
    if (path.startsWith('/agents')) {
      return [
        {
          id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001',
          name: 'Agent 1',
          archived_at: null,
        },
      ]
    }
    if (path.startsWith('/environments')) return []
    return []
  })
}

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

function webhookTrigger({
  secretRef = null,
  secretKey = null,
}: {
  secretRef?: string | null
  secretKey?: string | null
} = {}): AgentTrigger {
  return {
    ...completedOneOffTrigger(),
    id: OTHER_TRIGGER_ID,
    name: 'Inbound hook',
    type: 'webhook',
    prompt_template: '{{ body }}',
    cron_expr: null,
    timezone: null,
    run_at: null,
    next_run_at: null,
    last_fired_slot: null,
    secret_ref: secretRef,
    secret_key: secretKey,
    config: { auth_methods: ['hmac'] },
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
  beforeEach(() => {
    managedGetMock.mockReset()
    secretParserState.bypass = false
    mockManagedApi()
  })

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

  it('submits the selected Secret resource name and selected metadata key', async () => {
    const { getByText } = renderDialog(webhookTrigger())

    await waitFor(() => expect(getByText('hook-prod')).toBeTruthy())
    fireEvent.click(getByText('hook-prod'))
    fireEvent.click(getByText('ALT_TOKEN'))

    const saveButton = getByText('common.save').closest('button')
    expect(saveButton).not.toBeDisabled()
    fireEvent.click(saveButton!)

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0].body).toEqual(
      expect.objectContaining({ secret_ref: 'hook-prod', secret_key: 'ALT_TOKEN' }),
    )
  })

  it('preserves an unavailable historical Secret resource and disables save', async () => {
    const { getAllByText, getByText } = renderDialog(
      webhookTrigger({ secretRef: 'deleted-hook', secretKey: 'WEBHOOK_SECRET' }),
    )

    await waitFor(() =>
      expect(getAllByText('managed.triggers.serviceCredentialUnavailable').length).toBeGreaterThan(
        0,
      ),
    )
    expect(getByText('common.save').closest('button')).toBeDisabled()
  })

  it('preserves an unavailable historical Secret field and disables save', async () => {
    const { getByText } = renderDialog(
      webhookTrigger({ secretRef: 'hook-prod', secretKey: 'REMOVED_FIELD' }),
    )

    await waitFor(() =>
      expect(getByText('managed.triggers.credentialFieldUnavailable')).toBeTruthy(),
    )
    expect(getByText('common.save').closest('button')).toBeDisabled()
  })

  it('reports a Secret with no metadata keys and disables save', async () => {
    mockManagedApi({ keys: [] })
    const { getByText } = renderDialog(
      webhookTrigger({ secretRef: 'hook-prod', secretKey: null }),
    )

    await waitFor(() => expect(getByText('managed.triggers.credentialFieldEmpty')).toBeTruthy())
    expect(getByText('common.save').closest('button')).toBeDisabled()
  })

  it('never renders blank credential field items when malformed metadata bypasses parsing', async () => {
    secretParserState.bypass = true
    mockManagedApi({ keys: ['', '   ', 'WEBHOOK_SECRET'] })

    const view = renderDialog(
      webhookTrigger({ secretRef: 'hook-prod', secretKey: 'WEBHOOK_SECRET' }),
    )

    await waitFor(() => expect(view.getByText('WEBHOOK_SECRET')).toBeTruthy())
    const itemValues = [...view.baseElement.querySelectorAll('[data-select-value]')].map(
      (item) => item.getAttribute('data-select-value') ?? '',
    )
    expect(itemValues).toContain('WEBHOOK_SECRET')
    expect(itemValues.some((value) => !value.trim())).toBe(false)
    expect(view.getByText('common.save').closest('button')).not.toBeDisabled()
  })

  it('reports a failed Secret query and disables save', async () => {
    mockManagedApi({ secretError: new Error('secret metadata unavailable') })
    const { getByText } = renderDialog(
      webhookTrigger({ secretRef: 'hook-prod', secretKey: 'WEBHOOK_SECRET' }),
    )

    await waitFor(() =>
      expect(getByText('managed.triggers.serviceCredentialLoadFailed')).toBeTruthy(),
    )
    expect(getByText('common.save').closest('button')).toBeDisabled()
  })
})

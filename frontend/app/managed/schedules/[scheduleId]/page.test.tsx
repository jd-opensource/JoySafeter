import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pushMock = vi.fn()

interface RunRecord {
  id: string
  schedule_id: string | null
  status: string
  chat_session_id: string | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

interface ScheduleRecord {
  id: string
  name: string
  description: string | null
  agent_id: string
  prompt: string
  system_prompt: string | null
  cron_expr: string
  timezone: string
  enabled: boolean
  concurrency_policy: string
  timeout_sec: number
  max_retries: number
  next_run_at: string | null
  created_at: string
}

const hoisted = vi.hoisted(() => ({
  triggerMutate: vi.fn(),
  toggleMutate: vi.fn(),
  deleteMutate: vi.fn(),
  state: {
    schedule: null as ScheduleRecord | null,
    runs: [] as RunRecord[],
  },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

vi.mock('@/lib/managed/cron', () => ({
  describeCron: (expr: string) => `desc:${expr}`,
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/schedules/create-schedule-dialog', () => ({
  CreateScheduleDialog: () => null,
}))

vi.mock('@/lib/managed/schedules', () => ({
  useSchedule: () => ({
    data: hoisted.state.schedule,
    isLoading: false,
    isError: false,
    error: null,
  }),
  useScheduleRuns: () => ({
    data: hoisted.state.runs,
    isLoading: false,
    isFetching: false,
  }),
  useToggleSchedule: () => ({ mutateAsync: hoisted.toggleMutate, isPending: false }),
  useTriggerSchedule: () => ({ mutateAsync: hoisted.triggerMutate, isPending: false }),
  useDeleteSchedule: () => ({ mutateAsync: hoisted.deleteMutate, isPending: false }),
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    columns,
    data,
    emptyMessage,
  }: {
    columns: { key: string; render: (row: RunRecord) => ReactNode }[]
    data: RunRecord[]
    emptyMessage?: string
  }) => (
    <div>
      {data.length === 0 && <div>{emptyMessage}</div>}
      {data.map((row) => (
        <div key={row.id}>
          {columns.map((c) => (
            <span key={c.key}>{c.render(row)}</span>
          ))}
        </div>
      ))}
    </div>
  ),
  PageHeader: ({ title, action }: { title: string; action?: ReactNode }) => (
    <div>
      <h1>{title}</h1>
      {action}
    </div>
  ),
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ConfirmDialog: ({
    open,
    onConfirm,
    onCancel,
    confirmLabel,
  }: {
    open: boolean
    onConfirm: () => void
    onCancel: () => void
    confirmLabel?: string
  }) =>
    open ? (
      <div>
        <button onClick={onConfirm}>{confirmLabel || 'confirm'}</button>
        <button onClick={onCancel}>cancel-dialog</button>
      </div>
    ) : null,
  ResourceErrorState: () => null,
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    onClick,
    disabled,
  }: {
    children: ReactNode
    onClick?: () => void
    disabled?: boolean
  }) => (
    <button disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/switch', () => ({
  Switch: ({
    checked,
    disabled,
    onCheckedChange,
  }: {
    checked: boolean
    disabled?: boolean
    onCheckedChange?: (checked: boolean) => void
  }) => (
    <input
      type="checkbox"
      role="switch"
      checked={checked}
      disabled={disabled}
      onChange={(e) => onCheckedChange?.(e.target.checked)}
    />
  ),
}))

vi.mock('@/components/ui/card', () => ({
  Card: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { useProjectStore } from '@/stores/managed/project-store'

import ScheduleDetailPage from './page'

const SCHEDULE_UUID = '11111111-1111-4111-8111-111111111111'
const SCHEDULE_ID = `sched_${SCHEDULE_UUID}`
const AGENT_ID = 'agent_22222222-2222-4222-8222-222222222222'
const TASK_ID = 'task_33333333-3333-4333-8333-333333333333'
const SESSION_ID = 'sess_44444444-4444-4444-8444-444444444444'

function scheduleRecord(): ScheduleRecord {
  return {
    id: SCHEDULE_ID,
    name: 'Daily report',
    description: null,
    agent_id: AGENT_ID,
    prompt: 'Summarize yesterday',
    system_prompt: null,
    cron_expr: '0 9 * * *',
    timezone: 'UTC',
    enabled: true,
    concurrency_policy: 'allow',
    timeout_sec: 7200,
    max_retries: 2,
    next_run_at: '2026-07-11T09:00:00Z',
    created_at: '2026-07-10T00:00:00Z',
  }
}

function run(id: string, overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id,
    schedule_id: SCHEDULE_ID,
    status: 'completed',
    chat_session_id: SESSION_ID,
    error: null,
    created_at: '2026-07-10T09:00:00Z',
    started_at: '2026-07-10T09:00:01Z',
    completed_at: '2026-07-10T09:01:00Z',
    ...overrides,
  }
}

function activeProject() {
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
    },
    organizations: [],
    projects: [],
  })
}

function renderPage() {
  const params = {
    status: 'fulfilled',
    value: { scheduleId: SCHEDULE_ID },
    then: () => undefined,
  } as unknown as Promise<{ scheduleId: string }>
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ScheduleDetailPage params={params} />
    </QueryClientProvider>,
  )
}

describe('ScheduleDetailPage', () => {
  beforeEach(() => {
    hoisted.triggerMutate.mockReset().mockResolvedValue({})
    hoisted.deleteMutate.mockReset().mockResolvedValue({})
    hoisted.state.schedule = scheduleRecord()
    hoisted.state.runs = []
    pushMock.mockReset()
    activeProject()
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

  it('renders the schedule config and run history', () => {
    hoisted.state.runs = [run(TASK_ID)]
    const { getByText, getAllByText } = renderPage()
    expect(getByText('Daily report')).toBeTruthy()
    expect(getByText('desc:0 9 * * *')).toBeTruthy()
    expect(getByText('Summarize yesterday')).toBeTruthy()
    // The run's completed status renders in the history table.
    expect(getAllByText('completed').length).toBeGreaterThan(0)
  })

  it('shows the empty run message when there are no runs', () => {
    const { getByText } = renderPage()
    expect(getByText('managed.schedules.runs.empty')).toBeTruthy()
  })

  it('triggers a run from the detail header', async () => {
    const { getByText } = renderPage()
    await act(async () => {
      fireEvent.click(getByText('managed.schedules.runNow'))
    })
    expect(hoisted.triggerMutate).toHaveBeenCalledWith(SCHEDULE_UUID)
  })

  it('opens the scheduled run session using the managed session id', async () => {
    hoisted.state.runs = [run(TASK_ID)]
    const { getByText } = renderPage()

    await act(async () => {
      fireEvent.click(getByText('managed.schedules.runs.open'))
    })

    expect(pushMock).toHaveBeenCalledWith(`/managed/sessions/${SESSION_ID}`)
  })

  it('deletes the schedule after confirming and navigates back to the list', async () => {
    const { getByText, getAllByText } = renderPage()
    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })
    await act(async () => {
      fireEvent.click(getAllByText('common.delete').at(-1)!)
    })
    await waitFor(() => {
      expect(hoisted.deleteMutate).toHaveBeenCalledWith(SCHEDULE_UUID)
    })
    expect(pushMock).toHaveBeenCalledWith('/managed/schedules')
  })

  it('closes destructive confirmation state when the managed scope changes', async () => {
    const { getByText, getAllByText } = renderPage()
    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })
    expect(getAllByText('common.delete')).toHaveLength(2)

    await act(async () => {
      useProjectStore.setState({
        currentProjectId: 'project-b',
        currentProject: {
          id: 'project-b',
          org_id: 'org-a',
          name: 'Project B',
          slug: 'project-b',
          is_default: false,
          archived_at: null,
        },
      })
    })

    expect(getAllByText('common.delete')).toHaveLength(1)
  })

  it('hides write actions when the current project is archived', () => {
    useProjectStore.setState({
      currentProject: {
        id: 'project-a',
        org_id: 'org-a',
        name: 'Project A',
        slug: 'project-a',
        is_default: true,
        archived_at: '2026-07-01T00:00:00Z',
      },
    })
    const { queryByText } = renderPage()

    expect(queryByText('managed.schedules.runNow')).toBeNull()
    expect(queryByText('common.edit')).toBeNull()
    expect(queryByText('common.delete')).toBeNull()
  })
})

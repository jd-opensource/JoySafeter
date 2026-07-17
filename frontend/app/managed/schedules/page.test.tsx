import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pushMock = vi.fn()

const hoisted = vi.hoisted(() => ({
  triggerMutate: vi.fn(),
  toggleMutate: vi.fn(),
  deleteMutate: vi.fn(),
  state: { schedules: [] as ScheduleRecord[] },
}))

interface ScheduleRecord {
  id: string
  name: string
  description: string | null
  agent_id: string
  cron_expr: string
  timezone: string
  enabled: boolean
  concurrency_policy: string
  next_run_at: string | null
  created_at: string
}

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
  useSchedules: () => ({
    data: hoisted.state.schedules,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  }),
  useToggleSchedule: () => ({ mutateAsync: hoisted.toggleMutate, isPending: false }),
  useTriggerSchedule: () => ({ mutateAsync: hoisted.triggerMutate, isPending: false }),
  useDeleteSchedule: () => ({ mutateAsync: hoisted.deleteMutate, isPending: false }),
}))

vi.mock('@/components/managed/shared', () => ({
  DataTable: ({
    columns,
    data,
    actionMenu,
    emptyMessage,
  }: {
    columns: { key: string; render: (row: ScheduleRecord) => ReactNode }[]
    data: ScheduleRecord[]
    actionMenu?: (row: ScheduleRecord) => { label: string; onClick: () => void }[]
    emptyMessage?: string
  }) => (
    <div>
      {data.length === 0 && <div>{emptyMessage}</div>}
      {data.map((row) => (
        <div key={row.id}>
          {columns.map((c) => (
            <span key={c.key}>{c.render(row)}</span>
          ))}
          {actionMenu?.(row).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {row.id}:{item.label}
            </button>
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
  FilterBar: () => null,
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { useProjectStore } from '@/stores/managed/project-store'

import ScheduleListPage from './page'

const SCHEDULE_UUID = '11111111-1111-4111-8111-111111111111'
const SCHEDULE_ID = `sched_${SCHEDULE_UUID}`
const AGENT_ID = 'agent_22222222-2222-4222-8222-222222222222'

function schedule(
  id: string,
  name: string,
  overrides: Partial<ScheduleRecord> = {},
): ScheduleRecord {
  return {
    id,
    name,
    description: null,
    agent_id: AGENT_ID,
    cron_expr: '0 9 * * *',
    timezone: 'UTC',
    enabled: true,
    concurrency_policy: 'allow',
    next_run_at: '2026-07-11T09:00:00Z',
    created_at: '2026-07-10T00:00:00Z',
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

function requestScope(projectId = 'project-a') {
  return {
    orgId: 'org-a',
    projectId,
    key: `org-a:${projectId}`,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ScheduleListPage />
    </QueryClientProvider>,
  )
}

describe('ScheduleListPage', () => {
  beforeEach(() => {
    hoisted.triggerMutate.mockReset().mockResolvedValue({})
    hoisted.toggleMutate.mockReset().mockResolvedValue({})
    hoisted.deleteMutate.mockReset().mockResolvedValue({})
    hoisted.state.schedules = []
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

  it('renders schedule rows with a human-readable cron description', () => {
    hoisted.state.schedules = [schedule(SCHEDULE_ID, 'Daily report')]
    const { getByText } = renderPage()
    expect(getByText('Daily report')).toBeTruthy()
    expect(getByText('desc:0 9 * * *')).toBeTruthy()
  })

  it('shows the empty message when there are no schedules', () => {
    const { getByText } = renderPage()
    expect(getByText('managed.schedules.empty')).toBeTruthy()
  })

  it('triggers a run when "Run now" is clicked', async () => {
    hoisted.state.schedules = [schedule(SCHEDULE_ID, 'Daily report')]
    const { getByText } = renderPage()
    await act(async () => {
      fireEvent.click(getByText(`${SCHEDULE_ID}:managed.schedules.runNow`))
    })
    expect(hoisted.triggerMutate).toHaveBeenCalledWith({
      id: SCHEDULE_ID,
      requestScope: requestScope(),
    })
  })

  it('deletes a schedule after confirming', async () => {
    hoisted.state.schedules = [schedule(SCHEDULE_ID, 'Daily report')]
    const { getByText } = renderPage()
    await act(async () => {
      fireEvent.click(getByText(`${SCHEDULE_ID}:common.delete`))
    })
    await act(async () => {
      fireEvent.click(getByText('common.delete'))
    })
    expect(hoisted.deleteMutate).toHaveBeenCalledWith({
      id: SCHEDULE_ID,
      requestScope: requestScope(),
    })
  })

  it('toggles a schedule via the enabled switch', async () => {
    hoisted.state.schedules = [schedule(SCHEDULE_ID, 'Daily report', { enabled: true })]
    const { getByRole } = renderPage()
    await act(async () => {
      fireEvent.click(getByRole('switch'))
    })
    expect(hoisted.toggleMutate).toHaveBeenCalledWith({
      id: SCHEDULE_ID,
      enabled: false,
      requestScope: requestScope(),
    })
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
    hoisted.state.schedules = [schedule(SCHEDULE_ID, 'Daily report')]
    const { queryByText, getByText } = renderPage()
    expect(queryByText('managed.schedules.new')).toBeNull()
    expect(queryByText(`${SCHEDULE_ID}:managed.schedules.runNow`)).toBeNull()
    expect(getByText(`${SCHEDULE_ID}:managed.schedules.viewRuns`)).toBeTruthy()
  })
})

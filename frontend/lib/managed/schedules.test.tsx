import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { type Schedule, useSchedules, useToggleSchedule } from './schedules'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

const SCHEDULE_UUID = '11111111-1111-4111-8111-111111111111'
const SCHEDULE_ID = `sched_${SCHEDULE_UUID}`

function schedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: SCHEDULE_ID,
    name: 'Daily report',
    description: null,
    agent_id: 'agent_22222222-2222-4222-8222-222222222222',
    prompt: 'Run report',
    system_prompt: null,
    environment_ref: null,
    cron_expr: '0 9 * * *',
    timezone: 'UTC',
    enabled: true,
    concurrency_policy: 'allow',
    timeout_sec: 300,
    max_retries: 0,
    next_run_at: null,
    last_fired_slot: null,
    project_id: 'project-a',
    created_at: '2026-07-10T00:00:00Z',
    updated_at: '2026-07-10T00:00:00Z',
    ...overrides,
  }
}

function setProject(orgId: string, projectId: string) {
  useProjectStore.setState({
    currentOrgId: orgId,
    currentProjectId: projectId,
    currentProject: { id: projectId, name: projectId, slug: projectId, is_default: true },
    organizations: [{ id: orgId, name: orgId, slug: orgId, role: 'owner' }],
    projects: [{ id: projectId, name: projectId, slug: projectId, is_default: true }],
  })
}

function wrapper(queryClient: QueryClient) {
  return function TestWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('managed schedule hooks', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    localStorage.clear()
    setProject('org-a', 'project-a')
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

  it('binds schedule list requests to the query scope headers', async () => {
    managedGetMock.mockResolvedValue([])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderHook(() => useSchedules(), { wrapper: wrapper(queryClient) })

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/schedules', {
        headers: {
          'X-Org-Id': 'org-a',
          'X-Project-Id': 'project-a',
        },
        skipManagedContext: true,
      })
    })
  })

  it('optimistically updates only the active schedule query scope', async () => {
    managedPostMock.mockResolvedValue(schedule({ enabled: false }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData<Schedule[]>(
      ['schedules', 'org-a:project-a', '/schedules'],
      [schedule({ enabled: true, project_id: 'project-a' })],
    )
    queryClient.setQueryData<Schedule[]>(
      ['schedules', 'org-a:project-b', '/schedules'],
      [schedule({ enabled: true, project_id: 'project-b' })],
    )

    const { result } = renderHook(() => useToggleSchedule(), {
      wrapper: wrapper(queryClient),
    })

    await act(async () => {
      await result.current.mutateAsync({ id: SCHEDULE_ID, enabled: false })
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      `/schedules/${SCHEDULE_UUID}/disable`,
      {},
      {
        headers: {
          'X-Org-Id': 'org-a',
          'X-Project-Id': 'project-a',
        },
        skipManagedContext: true,
      },
    )
    expect(
      queryClient.getQueryData<Schedule[]>(['schedules', 'org-a:project-a', '/schedules'])?.[0]
        .enabled,
    ).toBe(false)
    expect(
      queryClient.getQueryData<Schedule[]>(['schedules', 'org-a:project-b', '/schedules'])?.[0]
        .enabled,
    ).toBe(true)
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

vi.mock('next-runtime-env', () => ({ env: vi.fn(() => undefined) }))
vi.mock('@/lib/auth/csrf', () => ({ getCsrfToken: vi.fn(() => null) }))
vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client')
  return {
    ...actual,
    apiGet: mocks.apiGet,
    apiPost: mocks.apiPost,
  }
})

import { runService } from '../runService'

describe('runService', () => {
  beforeEach(() => {
    mocks.apiGet.mockReset()
    mocks.apiPost.mockReset()
  })

  it('includes agent_name and search in listRuns query params', async () => {
    mocks.apiGet.mockResolvedValue({ items: [] })

    await runService.listRuns({
      runType: 'generic_agent',
      agentName: 'skill_creator',
      status: 'running',
      search: 'skill',
      limit: 20,
    })

    expect(mocks.apiGet).toHaveBeenCalledWith(
      'runs?run_type=generic_agent&agent_name=skill_creator&status=running&search=skill&limit=20',
    )
  })

  it('calls the generic active-run endpoint', async () => {
    mocks.apiGet.mockResolvedValue(null)

    await runService.findActiveRun({
      agentName: 'skill_creator',
      graphId: 'graph-123',
      threadId: 'thread-456',
    })

    expect(mocks.apiGet).toHaveBeenCalledWith(
      'runs/active?agent_name=skill_creator&graph_id=graph-123&thread_id=thread-456',
    )
  })

  it('calls the generic create-run endpoint', async () => {
    mocks.apiPost.mockResolvedValue({ run_id: 'run-1', thread_id: 'thread-1', status: 'queued' })

    await runService.createRun({
      agent_name: 'skill_creator',
      graph_id: 'graph-123',
      message: 'Build a skill',
      thread_id: 'thread-456',
      input: { edit_skill_id: 'skill-789' },
    })

    expect(mocks.apiPost).toHaveBeenCalledWith('runs', {
      agent_name: 'skill_creator',
      graph_id: 'graph-123',
      message: 'Build a skill',
      thread_id: 'thread-456',
      input: { edit_skill_id: 'skill-789' },
    })
  })
})

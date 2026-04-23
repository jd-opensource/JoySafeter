import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
}))

vi.mock('next-runtime-env', () => ({ env: vi.fn(() => undefined) }))
vi.mock('@/lib/auth/csrf', () => ({ getCsrfToken: vi.fn(() => null) }))
vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client')
  return {
    ...actual,
    apiPost: mocks.apiPost,
  }
})

import { executionAdapter } from '../executionAdapter'

describe('executionAdapter', () => {
  beforeEach(() => mocks.apiPost.mockReset())

  it('startRun posts to runs and returns run data', async () => {
    mocks.apiPost.mockResolvedValue({ id: 'run1', current_execution_id: 'exec1', status: 'queued' })
    const result = await executionAdapter.startRun({
      releaseId: 'rel1',
      prompt: 'test input',
      workspaceId: 'w1',
    })
    expect(mocks.apiPost).toHaveBeenCalledWith(
      'runs',
      expect.objectContaining({
        release_id: 'rel1',
        goal: 'test input',
        workspace_id: 'w1',
        trigger_source: 'api',
      }),
    )
    expect(result.id).toBe('run1')
    expect(result.current_execution_id).toBe('exec1')
  })

  it('startRun forwards optional threadId and taskId', async () => {
    mocks.apiPost.mockResolvedValue({ id: 'run2', current_execution_id: 'exec2', status: 'queued' })
    await executionAdapter.startRun({
      releaseId: 'rel1',
      prompt: 'test',
      workspaceId: 'w1',
      threadId: 'thread-abc',
      taskId: 'task-xyz',
    })
    expect(mocks.apiPost).toHaveBeenCalledWith(
      'runs',
      expect.objectContaining({
        thread_id: 'thread-abc',
        task_id: 'task-xyz',
      }),
    )
  })

  it('cancelRun posts to runs/{id}/cancel', async () => {
    mocks.apiPost.mockResolvedValue({})
    await executionAdapter.cancelRun('run1')
    expect(mocks.apiPost).toHaveBeenCalledWith('runs/run1/cancel', {})
  })

  it('injectMessage posts to executions/{id}/message', async () => {
    vi.mocked(mocks.apiPost).mockResolvedValue({})
    await executionAdapter.injectMessage('exec1', 'continue')
    expect(mocks.apiPost).toHaveBeenCalledWith('executions/exec1/message', { message: 'continue' })
  })

  it('startRun propagates errors thrown by apiPost', async () => {
    mocks.apiPost.mockRejectedValueOnce(new Error('API error: 400'))
    const promise = executionAdapter.startRun({ releaseId: 'rel1', prompt: 'test', workspaceId: 'w1' })
    await expect(promise).rejects.toThrow('API error: 400')
  })
})

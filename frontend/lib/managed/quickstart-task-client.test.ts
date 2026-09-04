import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet } from '@/lib/api-client'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSessionId } from '@/types/entity-id'

import {
  fetchLatestQuickstartTrialTask,
  quickstartTrialTaskQueryKey,
} from './quickstart-task-client'

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

const SESSION_ID = parseSessionId('sess_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001')
const TASK_ID = 'task_018f6f42-0a51-7cc4-98c8-4f6f0ca5f002'
const SCOPE = {
  organizationId: 'org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f003',
  projectId: 'project_018f6f42-0a51-7cc4-98c8-4f6f0ca5f004',
  key: 'org:project',
} as ManagedRequestScope

describe('quickstart trial task client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
  })

  it('owns the latest-task request path, scope, and strict parsing', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [
        {
          id: TASK_ID,
          status: 'running',
          created_at: '2026-09-04T00:00:00Z',
          started_at: null,
          completed_at: null,
          error: null,
        },
      ],
      has_more: true,
      first_id: TASK_ID,
      last_id: TASK_ID,
    })

    await expect(fetchLatestQuickstartTrialTask(SESSION_ID, SCOPE)).resolves.toMatchObject({
      id: TASK_ID,
      status: 'running',
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/tasks?session_id=${encodeURIComponent(SESSION_ID)}&limit=1`,
      managedRequestOptions(SCOPE),
    )
  })

  it('uses session identity in the query key', () => {
    expect(quickstartTrialTaskQueryKey(SCOPE.key, SESSION_ID)).toEqual([
      'quickstart-trial-task',
      SCOPE.key,
      SESSION_ID,
    ])
  })
})

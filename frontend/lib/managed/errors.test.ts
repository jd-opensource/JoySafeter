import { describe, expect, it } from 'vitest'

import { TASK_ID } from '@/test-utils/entity-ids'

import { ApiError } from '../api-client'

import {
  getOperationErrorMessage,
  getOperationErrorMessageWithDetails,
  parseApiError,
  shouldRetryManagedResourceError,
} from './errors'

const t = (key: string) => `translated:${key}`

describe('managed operation errors', () => {
  it('surfaces backend messages when no specific managed mapping exists', () => {
    const error = new ApiError(503, 'Service Unavailable', {
      code: 'SERVICE_UNAVAILABLE',
      message: 'Failed to enqueue task',
      source: 'runtime',
      retryable: true,
      user_action: 'retry',
    })

    expect(getOperationErrorMessage(t, error, 'common.operationFailed')).toBe(
      'Failed to enqueue task',
    )
  })

  it('keeps specific managed mappings ahead of raw messages', () => {
    const error = new ApiError(404, 'Not Found', {
      code: 'NOT_FOUND',
      message: 'Agent not found',
      source: 'api',
    })

    expect(getOperationErrorMessage(t, error, 'common.operationFailed')).toBe(
      'translated:managed.errors.resourceNotFound',
    )
  })

  it('uses codes instead of message substrings for archived resources', () => {
    const archivedByMessageOnly = new ApiError(409, 'Conflict', {
      code: 'CONFLICT',
      message: 'Resource is archived',
      source: 'api',
    })
    const archivedByCode = new ApiError(409, 'Conflict', {
      code: 'PROJECT_ARCHIVED',
      message: 'Project is archived',
      source: 'api',
    })

    expect(getOperationErrorMessage(t, archivedByMessageOnly, 'common.operationFailed')).toBe(
      'Resource is archived',
    )
    expect(getOperationErrorMessage(t, archivedByCode, 'common.operationFailed')).toBe(
      'translated:managed.errors.projectArchived',
    )
  })

  it('localizes agent lifecycle conflicts instead of exposing backend English', () => {
    const error = new ApiError(409, 'Conflict', {
      code: 'AGENT_ACTIVE_TASKS',
      message: 'Agent has active tasks. Stop or cancel them before archiving sessions.',
      source: 'api',
      retryable: true,
      user_action: 'retry',
    })

    expect(getOperationErrorMessage(t, error, 'common.operationFailed')).toBe(
      'translated:managed.errors.agentActiveTasks',
    )
  })

  it('uses codes instead of status for retry classification', () => {
    expect(
      shouldRetryManagedResourceError(
        0,
        new ApiError(404, 'Not Found', {
          code: 'AGENT_NOT_FOUND',
          message: 'Agent not found',
          source: 'api',
        }),
      ),
    ).toBe(false)
    expect(
      shouldRetryManagedResourceError(
        0,
        new ApiError(404, 'Not Found', {
          code: 'AGENT_LOOKUP_TIMEOUT',
          message: 'Lookup timed out',
          source: 'runtime',
          retryable: true,
        }),
      ),
    ).toBe(true)
  })

  it('can append structured diagnostics for investigation-focused surfaces', () => {
    const error = new ApiError(409, 'Conflict', {
      code: 'SKILL_VERSION_EXISTS',
      message: 'Version already exists',
      source: 'api',
      trace_id: 'trace-123',
    })

    expect(getOperationErrorMessageWithDetails(t, error, 'common.operationFailed')).toBe(
      'Version already exists (SKILL_VERSION_EXISTS, HTTP 409, api, trace trace-123)',
    )
  })

  it('parses the canonical top-level envelope only', () => {
    expect(
      parseApiError({
        code: 'TASK_ENQUEUE_FAILED',
        message: 'Failed to enqueue task',
        data: { task_id: TASK_ID },
        source: 'runtime',
        payload: { code: 'OLD_SHAPE' },
      }),
    ).toMatchObject({
      code: 'TASK_ENQUEUE_FAILED',
      message: 'Failed to enqueue task',
      data: { task_id: TASK_ID },
      source: 'runtime',
    })
  })
})

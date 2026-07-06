import { describe, expect, it } from 'vitest'

import { ApiError } from '../api-client'
import { getOperationErrorMessage } from './errors'

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
})

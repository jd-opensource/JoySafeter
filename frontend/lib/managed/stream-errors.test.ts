import { describe, expect, it } from 'vitest'

import { getManagedStreamErrorMessage } from './stream-errors'

const t = (key: string) => key

describe('managed stream error messages', () => {
  it('keeps structured SSE error fields visible', () => {
    expect(
      getManagedStreamErrorMessage(
        t,
        {
          message: 'Rate limited by upstream API. Please try again later.',
          code: 'UPSTREAM_RATE_LIMITED',
          status: 429,
          source: 'upstream',
        },
        'common.operationFailed',
      ),
    ).toBe(
      'Rate limited by upstream API. Please try again later. (UPSTREAM_RATE_LIMITED, HTTP 429, upstream)',
    )
  })

  it('falls back when the stream event has no message', () => {
    expect(getManagedStreamErrorMessage(t, { code: 'UPSTREAM_STREAM_ERROR' }, 'fallback.key')).toBe(
      'fallback.key (UPSTREAM_STREAM_ERROR)',
    )
  })
})

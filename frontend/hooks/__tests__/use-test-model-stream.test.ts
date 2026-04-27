import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const apiStream = vi.fn()

vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client')
  return {
    ...actual,
    apiStream: (...args: unknown[]) => apiStream(...args),
  }
})

import { useTestModelStream } from '../use-test-model-stream'

describe('useTestModelStream', () => {
  it('surfaces a canonical error when the stream has no response body', async () => {
    apiStream.mockResolvedValue({
      body: null,
    })

    const { result } = renderHook(() => useTestModelStream())

    await result.current.run({
      model_name: 'gpt-5',
      input: 'hello',
    })

    expect(result.current.error).toEqual({
      code: 'MODEL_STREAM_RESPONSE_INVALID',
      message: 'No response body',
      data: null,
    })
    expect(result.current.isStreaming).toBe(false)
  })
})

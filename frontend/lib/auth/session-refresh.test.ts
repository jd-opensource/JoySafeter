import { QueryClient } from '@tanstack/react-query'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from './api-client'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('silent session refresh lifecycle', () => {
  let refreshTokenMock: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    refreshTokenMock = vi.spyOn(authApi, 'refreshToken')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not invalidate an old query client after refresh cleanup', async () => {
    const { startSilentSessionRefresh } = await import('./session-refresh')
    const refresh = deferred<void>()
    refreshTokenMock.mockReturnValueOnce(refresh.promise)
    vi.spyOn(Date, 'now').mockReturnValue(9_999_999_999_999)
    const queryClient = new QueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const stopRefresh = startSilentSessionRefresh(queryClient)
    window.dispatchEvent(new dom.window.Event('focus'))
    expect(refreshTokenMock).toHaveBeenCalledTimes(1)

    stopRefresh()

    refresh.resolve()
    await refresh.promise
    await Promise.resolve()

    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('invalidates only the auth session query after silent refresh', async () => {
    const { startSilentSessionRefresh } = await import('./session-refresh')
    refreshTokenMock.mockResolvedValueOnce(undefined)
    vi.spyOn(Date, 'now').mockReturnValue(10_000_000_099_999)
    const queryClient = new QueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const stopRefresh = startSilentSessionRefresh(queryClient)
    try {
      window.dispatchEvent(new dom.window.Event('focus'))
      await Promise.resolve()
      await Promise.resolve()

      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['session'], exact: true })
    } finally {
      stopRefresh()
    }
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as apiClient from '@/lib/api-client'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/logs/console/logger', () => ({
  createLogger: () => ({
    error: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
  }),
}))

vi.mock('@/lib/utils/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/signin',
})
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>)
}

function providerResponse() {
  return {
    providers: [
      {
        id: 'github',
        display_name: 'GitHub',
        icon: 'github',
      },
    ],
  }
}

function authorizationRequestCount() {
  const managedGetMock = apiClient.managedGet as unknown as ReturnType<typeof vi.fn>
  return managedGetMock.mock.calls.filter(([path]) => String(path).startsWith('auth/oauth/github'))
    .length
}

describe('OAuthButtons lifecycle', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/signin')
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('does not redirect from an OAuth authorization response after unmount', async () => {
    const authorization = deferred<{ authorization_url: string; state: string }>()
    vi.spyOn(apiClient, 'managedGet').mockImplementation((path) => {
      if (String(path).startsWith('auth/oauth/github')) {
        return authorization.promise as ReturnType<typeof apiClient.managedGet>
      }
      return Promise.resolve(providerResponse()) as ReturnType<typeof apiClient.managedGet>
    })
    const { OAuthButtons } = await import('./oauth-buttons')
    const view = renderWithQueryClient(<OAuthButtons />)

    fireEvent.click(await view.findByText('auth.signInWith'))

    await waitFor(() => expect(authorizationRequestCount()).toBe(1))

    view.unmount()

    await act(async () => {
      authorization.resolve({ authorization_url: '/signin#oauth', state: 'state_1' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('does not let an older OAuth authorization response override a newer click', async () => {
    const olderAuthorization = deferred<{ authorization_url: string; state: string }>()
    const newerAuthorization = deferred<{ authorization_url: string; state: string }>()
    let authRequestCount = 0
    vi.spyOn(apiClient, 'managedGet').mockImplementation((path) => {
      if (String(path).startsWith('auth/oauth/github')) {
        authRequestCount += 1
        return (
          authRequestCount === 1 ? olderAuthorization.promise : newerAuthorization.promise
        ) as ReturnType<typeof apiClient.managedGet>
      }
      return Promise.resolve(providerResponse()) as ReturnType<typeof apiClient.managedGet>
    })

    const { OAuthButtons } = await import('./oauth-buttons')
    const view = renderWithQueryClient(<OAuthButtons />)

    const button = await view.findByText('auth.signInWith')
    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(authorizationRequestCount()).toBeGreaterThanOrEqual(2))

    await act(async () => {
      newerAuthorization.resolve({ authorization_url: '/signin#newer', state: 'state_2' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin#newer')

    await act(async () => {
      olderAuthorization.resolve({ authorization_url: '/signin#older', state: 'state_1' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin#newer')
  })
})

import { act, renderHook } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useQuickstartChat } from './use-quickstart-chat'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@/lib/auth/csrf', () => ({
  getCsrfToken: () => null,
}))

const originalFetch = globalThis.fetch
const dom = new JSDOM('<!doctype html><html><body></body></html>')

Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  Element: dom.window.Element,
  HTMLElement: dom.window.HTMLElement,
})
Object.defineProperty(globalThis, 'navigator', {
  value: dom.window.navigator,
  configurable: true,
})

describe('useQuickstartChat resource creation', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('does not mark an environment created when the create API fails', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(new Response('no image builder', { status: 500 })) as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let created: boolean | undefined
    await act(async () => {
      created = await result.current.createEnvironment('limited', ['api.example.com'])
    })

    expect(created).toBe(false)
    expect(result.current.resourceIds[4]).toBeUndefined()
    expect(result.current.completedSteps.has(4)).toBe(false)
    expect(result.current.messages.at(-1)?.content).toContain('API 500')
  })

  it('requires an environment id before marking the environment step complete', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json({
          success: true,
          data: { name: 'quickstart-env' },
        }),
      ) as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let created: boolean | undefined
    await act(async () => {
      created = await result.current.createEnvironment('unrestricted', [])
    })

    expect(created).toBe(false)
    expect(result.current.resourceIds[4]).toBeUndefined()
    expect(result.current.completedSteps.has(4)).toBe(false)
  })

  it('marks a vault created only after the create API returns an id', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json({
          success: true,
          data: { id: 'vlt_123' },
        }),
      ) as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let created: boolean | undefined
    await act(async () => {
      created = await result.current.createVault('prod-secrets')
    })

    expect(created).toBe(true)
    expect(result.current.resourceIds[5]).toBe('vlt_123')
    expect(result.current.completedSteps.has(5)).toBe(true)
  })
})

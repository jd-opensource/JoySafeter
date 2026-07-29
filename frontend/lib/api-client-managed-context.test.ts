import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-runtime-env', () => ({
  env: vi.fn(() => undefined),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

let apiFetch: typeof import('./api-client').apiFetch
let useProjectStore: typeof import('@/stores/managed/project-store').useProjectStore

describe('apiFetch managed context headers', () => {
  let originalFetch: typeof fetch | undefined

  beforeAll(async () => {
    const apiClientModule = await import('./api-client')
    const projectStoreModule = await import('@/stores/managed/project-store')
    apiFetch = apiClientModule.apiFetch
    useProjectStore = projectStoreModule.useProjectStore
  })

  beforeEach(() => {
    originalFetch = globalThis.fetch
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
  })

  afterEach(() => {
    if (originalFetch) {
      globalThis.fetch = originalFetch
    } else {
      delete (globalThis as { fetch?: typeof fetch }).fetch
    }
    vi.restoreAllMocks()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null })
    localStorage.clear()
  })

  it('adds both managed org and project headers to direct authenticated requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { ok: true } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await apiFetch('tasks')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      'X-Org-Id': 'org-a',
      'X-Project-Id': 'project-a',
    })
  })

  it('does not add managed context headers when explicitly skipped', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { ok: true } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await apiFetch('auth/session', { skipManagedContext: true })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.headers).not.toMatchObject({
      'X-Org-Id': 'org-a',
      'X-Project-Id': 'project-a',
    })
  })

  it('preserves explicit managed context headers from the caller', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { ok: true } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await apiFetch('tasks', {
      headers: {
        'X-Org-Id': 'org-custom',
        'X-Project-Id': 'project-custom',
      },
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      'X-Org-Id': 'org-custom',
      'X-Project-Id': 'project-custom',
    })
  })
})

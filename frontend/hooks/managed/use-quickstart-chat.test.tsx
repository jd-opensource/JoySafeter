import { act, renderHook } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/stores/managed/project-store'

import { useQuickstartChat } from './use-quickstart-chat'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@/lib/api-client', () => {
  class MockApiError extends Error {
    code: string

    constructor(
      public readonly status = 500,
      message = `API ${status}`,
    ) {
      super(message)
      this.name = 'ApiError'
      this.code = `HTTP_${status}`
    }
  }

  const base = 'http://localhost:8000/api/v1'
  const urlFor = (path: string) => `${base}/${path.replace(/^\/+/, '')}`
  const postRequest = (
    path: string,
    body?: unknown,
    options?: { signal?: AbortSignal; headers?: HeadersInit },
  ) =>
    fetch(urlFor(path), {
      method: 'POST',
      headers: options?.headers,
      body: JSON.stringify(body),
      signal: options?.signal,
    })

  return {
    ApiError: MockApiError,
    MANAGED_API_BASE: base,
    apiStream: vi.fn(postRequest),
    extractErrorFromResponse: vi.fn(
      async (response: Response) => new MockApiError(response.status, `API ${response.status}`),
    ),
    managedPost: vi.fn(async (path: string, body?: unknown, options?: { signal?: AbortSignal }) => {
      const response = await postRequest(path, body, options)
      if (!response.ok) throw new MockApiError(response.status, `API ${response.status}`)
      const json = await response.json().catch(() => undefined)
      return json?.data ?? json
    }),
  }
})

vi.mock('@/lib/auth/csrf', () => ({
  getCsrfToken: () => null,
}))

const originalFetch = globalThis.fetch
const dom = new JSDOM('<!doctype html><html><body></body></html>')
const encoder = new TextEncoder()

function quickstartAgentConfigResponse(resourceId?: string): Response {
  const stream = new ReadableStream({
    start(controller) {
      for (const event of [
        {
          type: 'config_update',
          step: 2,
          config: { name: 'Research Agent', system_prompt: 'Research carefully.' },
        },
        {
          type: 'step_complete',
          step: 2,
          curl: 'curl -X POST /agents',
          ...(resourceId ? { resource_id: resourceId } : {}),
        },
      ]) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.close()
    },
  })
  return new Response(stream, { status: 200 })
}

function controllableQuickstartResponse() {
  let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller
    },
  })
  return {
    response: new Response(stream, { status: 200 }),
    enqueue(event: unknown) {
      controllerRef?.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
    },
    close() {
      controllerRef?.close()
    },
  }
}

function quickstartResponseText(text: string): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(text))
        controller.close()
      },
    }),
    { status: 200 },
  )
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function setCurrentProject(archivedAt: string | null = null) {
  useProjectStore.setState({
    currentOrgId: 'org-a',
    currentProjectId: 'project-a',
    currentProject: {
      id: 'project-a',
      org_id: 'org-a',
      name: 'Project A',
      slug: 'project-a',
      is_default: true,
      archived_at: archivedAt,
    },
    organizations: [],
    projects: [],
  })
}

function expectManagedHeaders(call: unknown[] | undefined, projectId = 'project-a') {
  expect(call).toBeTruthy()
  const init = (call?.[1] ?? {}) as RequestInit
  expect(init.headers).toMatchObject({
    'X-Org-Id': 'org-a',
    'X-Project-Id': projectId,
  })
}

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
  beforeEach(() => {
    setCurrentProject()
  })

  afterEach(async () => {
    globalThis.fetch = originalFetch
    await act(async () => {
      useProjectStore.setState({
        currentOrgId: null,
        currentProjectId: null,
        currentProject: null,
        organizations: [],
        projects: [],
      })
      await wait(0)
    })
    vi.restoreAllMocks()
  })

  it('does not start quickstart generation or create resources when the current project is archived', async () => {
    setCurrentProject('2026-07-10T00:00:00Z')
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let environmentCreated: boolean | undefined
    let vaultCreated: boolean | undefined
    let generated = ''

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
      environmentCreated = await result.current.createEnvironment('limited', ['api.example.com'])
      vaultCreated = await result.current.createVault('prod-secrets')
      generated = await result.current.generateTestMessage()
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(environmentCreated).toBe(false)
    expect(vaultCreated).toBe(false)
    expect(generated).toBe('managed.quickstart.trialRun.defaultPrompt')
    expect(result.current.messages).toEqual([])
    expect(result.current.resourceIds).toEqual({})
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
    globalThis.fetch = vi.fn().mockResolvedValue(
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
    globalThis.fetch = vi.fn().mockResolvedValue(
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

  it('does not mark an environment created after the hook unmounts', async () => {
    const createEnvironmentResponse = deferred<Response>()
    const fetchMock = vi.fn().mockReturnValueOnce(createEnvironmentResponse.promise)
    globalThis.fetch = fetchMock as typeof fetch

    const { result, unmount } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let createdPromise!: Promise<boolean | undefined>
    await act(async () => {
      createdPromise = result.current.createEnvironment('unrestricted', [])
      await Promise.resolve()
    })

    unmount()

    let created: boolean | undefined
    await act(async () => {
      createEnvironmentResponse.resolve(
        Response.json({
          success: true,
          data: { id: 'env_after_unmount' },
        }),
      )
      created = await createdPromise
    })

    expect(created).toBe(false)
  })

  it('does not mark a vault created after the hook unmounts', async () => {
    const createVaultResponse = deferred<Response>()
    const fetchMock = vi.fn().mockReturnValueOnce(createVaultResponse.promise)
    globalThis.fetch = fetchMock as typeof fetch

    const { result, unmount } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let createdPromise!: Promise<boolean | undefined>
    await act(async () => {
      createdPromise = result.current.createVault('prod-secrets')
      await Promise.resolve()
    })

    unmount()

    let created: boolean | undefined
    await act(async () => {
      createVaultResponse.resolve(
        Response.json({
          success: true,
          data: { id: 'vault_after_unmount' },
        }),
      )
      created = await createdPromise
    })

    expect(created).toBe(false)
  })

  it('keeps generated-step confirmation available when confirmed creation fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse())
      .mockResolvedValueOnce(new Response('agent create failed', { status: 500 }))
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    expect(result.current.pendingConfirmation).toEqual({
      step: 3,
      curl: 'curl -X POST /agents',
    })

    await act(async () => {
      await result.current.confirmStep()
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.pendingConfirmation).toEqual({
      step: 3,
      curl: 'curl -X POST /agents',
    })
    expect(result.current.resourceIds[3]).toBeUndefined()
    expect(result.current.completedSteps.has(3)).toBe(false)
    expect(result.current.messages.at(-1)?.content).toContain('API 500')
  })

  it('requires an id from confirmed generated resource creation before completing the step', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse())
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { name: 'Research Agent' },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    await act(async () => {
      await result.current.confirmStep()
    })

    expect(result.current.pendingConfirmation).toEqual({
      step: 3,
      curl: 'curl -X POST /agents',
    })
    expect(result.current.resourceIds[3]).toBeUndefined()
    expect(result.current.completedSteps.has(3)).toBe(false)
  })

  it('tracks a confirmed generated agent as a quickstart-created resource', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse())
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'agent_created', model: { id: 'claude-sonnet-4-5' } },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    await act(async () => {
      await result.current.confirmStep()
    })

    expect(result.current.resourceIds[3]).toBe('agent_created')
    expect(result.current.createdResourceIds.has('agent_created')).toBe(true)
  })

  it('requires a session id before marking session creation complete', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse('agent_123'))
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { status: 'running' },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    expect(result.current.resourceIds[3]).toBe('agent_123')

    await act(async () => {
      await result.current.createSession()
    })

    expect(result.current.resourceIds[6]).toBeUndefined()
    expect(result.current.completedSteps.has(6)).toBe(false)
    expect(result.current.messages.at(-1)?.content).toBe(
      'managed.quickstart.errors.createSessionFailed',
    )
  })

  it('uses validated session resource overrides instead of stale stored environment and vault ids', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse('agent_123'))
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'env_stale' },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'vlt_stale' },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'session_123' },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    await act(async () => {
      await result.current.createEnvironment('unrestricted', [])
    })
    await act(async () => {
      await result.current.createVault('prod-secrets')
    })

    expect(result.current.resourceIds).toMatchObject({
      3: 'agent_123',
      4: 'env_stale',
      5: 'vlt_stale',
    })

    await act(async () => {
      await result.current.createSession({ environmentId: null, vaultId: null })
    })

    const sessionCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/sessions'))
    expect(sessionCall).toBeTruthy()
    expectManagedHeaders(sessionCall)
    expect(JSON.parse(sessionCall?.[1]?.body as string)).toEqual({ agent: '123' })
  })

  it('does not create a session from an old quickstart closure in the same turn as a project switch', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse('agent_a'))
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'env_a' },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'vlt_a' },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    await act(async () => {
      await result.current.createEnvironment('unrestricted', [])
    })
    await act(async () => {
      await result.current.createVault('prod-secrets')
    })

    expect(result.current.resourceIds).toMatchObject({
      3: 'agent_a',
      4: 'env_a',
      5: 'vlt_a',
    })

    const createSessionFromProjectA = result.current.createSession

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await createSessionFromProjectA()
    })

    const sessionCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sessions'))
    expect(sessionCalls).toHaveLength(0)
    expect(result.current.resourceIds[6]).toBeUndefined()
  })

  it('does not append or lock streaming from an old chat closure after a same-turn project switch', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const fetchMock = vi.fn().mockResolvedValue(quickstartAgentConfigResponse('agent_a'))
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))
    const oldSendMessage = result.current.sendMessage

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await oldSendMessage('make an agent', { stepOverride: 3 })
      await wait(0)
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.messages).toEqual([])
    expect(result.current.isStreaming).toBe(false)
  })

  it('does not mark a session created after the managed project changes while the request is in flight', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const createSessionResponse = deferred<Response>()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse('agent_a'))
      .mockReturnValueOnce(createSessionResponse.promise)
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    expect(result.current.resourceIds[3]).toBe('agent_a')

    let sessionPromise!: Promise<void>
    await act(async () => {
      sessionPromise = result.current.createSession()
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    await act(async () => {
      createSessionResponse.resolve(
        Response.json({
          success: true,
          data: { id: 'session_after_project_switch' },
        }),
      )
      await sessionPromise
    })

    expect(result.current.resourceIds[6]).toBeUndefined()
    expect(result.current.completedSteps.has(6)).toBe(false)
  })

  it('does not confirm a generated resource after the managed project changes while creation is in flight', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const createAgentResponse = deferred<Response>()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse())
      .mockReturnValueOnce(createAgentResponse.promise)
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    expect(result.current.pendingConfirmation).toEqual({
      step: 3,
      curl: 'curl -X POST /agents',
    })

    let confirmPromise!: Promise<void>
    await act(async () => {
      confirmPromise = result.current.confirmStep()
      await Promise.resolve()
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    await act(async () => {
      createAgentResponse.resolve(
        Response.json({
          success: true,
          data: { id: 'agent_after_project_switch' },
        }),
      )
      await confirmPromise
    })

    expect(result.current.resourceIds[3]).toBeUndefined()
    expect(result.current.completedSteps.has(3)).toBe(false)
  })

  it('does not confirm a pending generated resource after the current project is archived', async () => {
    setCurrentProject(null)
    const fetchMock = vi.fn().mockResolvedValueOnce(quickstartAgentConfigResponse())
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    expect(result.current.pendingConfirmation).toEqual({
      step: 3,
      curl: 'curl -X POST /agents',
    })

    await act(async () => {
      setCurrentProject('2026-07-10T00:00:00Z')
      await result.current.confirmStep()
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(result.current.resourceIds[3]).toBeUndefined()
    expect(result.current.completedSteps.has(3)).toBe(false)
    expect(result.current.pendingConfirmation).toEqual({
      step: 3,
      curl: 'curl -X POST /agents',
    })
  })

  it('does not start a second chat stream while the first stream is still open', async () => {
    const first = controllableQuickstartResponse()
    const second = controllableQuickstartResponse()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(first.response)
      .mockResolvedValueOnce(second.response)
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let firstSend!: Promise<void>
    let secondSend!: Promise<void>
    await act(async () => {
      firstSend = result.current.sendMessage('make an agent', { stepOverride: 3 })
      secondSend = result.current.sendMessage('make another agent', { stepOverride: 3 })
      await wait(10)
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)

    first.close()
    second.close()
    await act(async () => {
      await firstSend
      await secondSend
    })
  })

  it('aborts the current chat stream when the hook unmounts', async () => {
    const stream = controllableQuickstartResponse()
    const fetchMock = vi.fn().mockResolvedValueOnce(stream.response)
    globalThis.fetch = fetchMock as typeof fetch

    const { result, unmount } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let send!: Promise<void>
    await act(async () => {
      send = result.current.sendMessage('make an agent', { stepOverride: 3 })
      await wait(10)
    })

    const signal = fetchMock.mock.calls[0][1]?.signal as AbortSignal
    expect(signal.aborted).toBe(false)

    unmount()

    expect(signal.aborted).toBe(true)

    stream.close()
    await act(async () => {
      await send
    })
  })

  it('does not apply late stream events from the previous managed project', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const stream = controllableQuickstartResponse()
    const fetchMock = vi.fn().mockResolvedValueOnce(stream.response)
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let send!: Promise<void>
    await act(async () => {
      send = result.current.sendMessage('make an agent', { stepOverride: 3 })
      await wait(10)
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    await act(async () => {
      stream.enqueue({
        type: 'step_complete',
        step: 2,
        resource_id: 'agent_from_project_a',
        curl: 'curl -X POST /agents',
      })
      stream.close()
      await send
    })

    expect(result.current.resourceIds[3]).toBeUndefined()
    expect(result.current.pendingConfirmation).toBeNull()
  })

  it('applies a final config update when the stream closes without a trailing newline', async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(
      quickstartResponseText(
        `data: ${JSON.stringify({
          type: 'config_update',
          step: 2,
          config: { name: 'Terminal Agent', system_prompt: 'Use the final frame.' },
        })}`,
      ),
    ) as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })

    expect(result.current.config.agent).toMatchObject({
      name: 'Terminal Agent',
      system_prompt: 'Use the final frame.',
    })
  })

  it('does not let old stream cleanup stop a new managed project stream indicator', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const oldStream = controllableQuickstartResponse()
    const newStream = controllableQuickstartResponse()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(oldStream.response)
      .mockResolvedValueOnce(newStream.response)
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    let oldSend!: Promise<void>
    await act(async () => {
      oldSend = result.current.sendMessage('make an agent', { stepOverride: 3 })
      await wait(10)
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    let newSend!: Promise<void>
    await act(async () => {
      newSend = result.current.sendMessage('make a project-b agent', { stepOverride: 3 })
      await wait(10)
    })

    expectManagedHeaders(fetchMock.mock.calls[0], 'project-a')
    expectManagedHeaders(fetchMock.mock.calls[1], 'project-b')

    await act(async () => {
      oldStream.close()
      await oldSend
    })

    expect(result.current.isStreaming).toBe(true)
    expect(result.current.messages.at(-1)?.content).toBe('')
    expect(result.current.messages.at(-1)?.isStreaming).toBe(true)

    newStream.close()
    await act(async () => {
      await newSend
    })
  })

  it('does not generate a test message from an old quickstart closure after a same-turn project switch', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const fetchMock = vi.fn().mockResolvedValueOnce(quickstartAgentConfigResponse('agent_a'))
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })

    const oldGenerateTestMessage = result.current.generateTestMessage
    fetchMock.mockClear()

    let generated = ''
    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      generated = await oldGenerateTestMessage()
      await wait(0)
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(generated).toBe('managed.quickstart.trialRun.defaultPrompt')
  })

  it('does not create a session with resource ids from the previous managed project', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse('agent_a'))
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'env_a' },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'vlt_a' },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          success: true,
          data: { id: 'sess_should_not_be_created' },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })
    await act(async () => {
      await result.current.createEnvironment('unrestricted', [])
    })
    await act(async () => {
      await result.current.createVault('prod-secrets')
    })

    expect(result.current.resourceIds).toMatchObject({
      3: 'agent_a',
      4: 'env_a',
      5: 'vlt_a',
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    await act(async () => {
      await result.current.createSession()
    })

    const sessionCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sessions'))
    expect(sessionCalls).toHaveLength(0)
    expect(result.current.resourceIds[6]).toBeUndefined()
    expect(result.current.messages.at(-1)?.content).toBe(
      'managed.quickstart.errors.agentMissingForSession',
    )
  })

  it('does not create a session after the current project is archived with an agent already in quickstart state', async () => {
    setCurrentProject(null)

    const fetchMock = vi.fn().mockResolvedValueOnce(quickstartAgentConfigResponse('agent_a'))
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })

    expect(result.current.resourceIds[3]).toBe('agent_a')

    await act(async () => {
      setCurrentProject('2026-07-10T00:00:00Z')
      await result.current.createSession()
    })

    const sessionCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sessions'))
    expect(sessionCalls).toHaveLength(0)
    expect(result.current.resourceIds[6]).toBeUndefined()
    expect(result.current.completedSteps.has(6)).toBe(false)
  })

  it('keeps a generated test message final text delta when the stream closes without a trailing newline', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(quickstartAgentConfigResponse('agent_123'))
      .mockResolvedValueOnce(
        quickstartResponseText(
          `data: ${JSON.stringify({
            type: 'text_delta',
            text: 'Ask the research agent to compare two papers.',
          })}`,
        ),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const { result } = renderHook(() => useQuickstartChat('anthropic-prod'))

    await act(async () => {
      await result.current.sendMessage('make an agent', { stepOverride: 3 })
    })

    let generated = ''
    await act(async () => {
      generated = await result.current.generateTestMessage()
    })

    expect(generated).toBe('Ask the research agent to compare two papers.')
  })
})

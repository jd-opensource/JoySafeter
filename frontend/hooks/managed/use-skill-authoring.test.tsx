import { act, cleanup, renderHook } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-client', () => ({
  ApiError: class ApiError extends Error {
    code: string

    constructor(code = 'ERROR') {
      super(code)
      this.code = code
    }
  },
  apiStream: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

import { ApiError, apiStream, managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import { parseSkillId, type SkillId } from '@/types/entity-id'

import { useSkillAuthoring } from './use-skill-authoring'

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost',
})
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

const apiStreamMock = apiStream as unknown as ReturnType<typeof vi.fn>
const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

const PROJECT_SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f101'
const UNMOUNTED_SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f102'
const SCAN_SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f103'
const PUBLISH_SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f104'
const BLOCKED_SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f105'
const SCAN_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f106'
const PROJECT_SKILL_ID = parseSkillId(`skill_${PROJECT_SKILL_UUID}`)
const UNMOUNTED_SKILL_ID = parseSkillId(`skill_${UNMOUNTED_SKILL_UUID}`)
const SCAN_SKILL_ID = parseSkillId(`skill_${SCAN_SKILL_UUID}`)
const PUBLISH_SKILL_ID = parseSkillId(`skill_${PUBLISH_SKILL_UUID}`)
const BLOCKED_SKILL_ID = parseSkillId(`skill_${BLOCKED_SKILL_UUID}`)

function scanResponse(status: string) {
  return {
    id: `sklscan_${SCAN_UUID}`,
    skill_id: SCAN_SKILL_ID,
    status,
  }
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

function controllableStreamResponse() {
  let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller
    },
  })

  return {
    response: new Response(stream, { status: 200 }),
    enqueue(event: unknown) {
      controllerRef?.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`))
    },
    close() {
      controllerRef?.close()
    },
  }
}

function streamResponseText(text: string) {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text))
        controller.close()
      },
    }),
    { status: 200 },
  )
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    capability: 'write',
    archived_at: archivedAt,
  }
}

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
}

describe('useSkillAuthoring stream lifecycle', () => {
  beforeEach(() => {
    apiStreamMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo(),
    })
    window.localStorage.clear()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    useProjectStore.setState({ currentOrgId: null, currentProjectId: null, currentProject: null })
    window.localStorage.clear()
  })

  it('does not hydrate a persisted draft from a different managed project', () => {
    window.localStorage.setItem(
      'joysafeter:skill-authoring-state:v1',
      JSON.stringify({
        messages: [{ role: 'user', content: 'project-a request' }],
        draft: {
          name: 'project-a-skill',
          description: '',
          tags: [],
          visibility: 'project',
          content: 'project A only',
          files: [],
        },
        draftSkillId: PROJECT_SKILL_ID,
      }),
    )
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })

    const { result } = renderHook(() => useSkillAuthoring())

    expect(result.current.messages).toEqual([])
    expect(result.current.draft.name).toBe('')
    expect(result.current.draftSkillId).toBeNull()
  })

  it('does not start a second authoring stream while the first stream is still open', async () => {
    const first = controllableStreamResponse()
    const second = controllableStreamResponse()
    apiStreamMock.mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response)

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    let firstSend!: Promise<void>
    let secondSend!: Promise<void>
    await act(async () => {
      firstSend = result.current.send('build a skill', 'openai-prod')
      secondSend = result.current.send('build another skill', 'openai-prod')
      await wait(10)
    })

    expect(apiStreamMock).toHaveBeenCalledTimes(1)

    first.close()
    second.close()
    await act(async () => {
      await firstSend
      await secondSend
    })
  })

  it('aborts the current stream on cancel and allows a new stream afterward', async () => {
    const first = controllableStreamResponse()
    const second = controllableStreamResponse()
    apiStreamMock.mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response)

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    let firstSend!: Promise<void>
    await act(async () => {
      firstSend = result.current.send('build a skill', 'openai-prod')
      await wait(10)
    })

    const firstSignal = apiStreamMock.mock.calls[0][2]?.signal as AbortSignal
    expect(apiStreamMock.mock.calls[0][2]).toMatchObject(managedOptions())
    expect(firstSignal.aborted).toBe(false)

    await act(async () => {
      result.current.cancel()
      await wait(10)
    })

    expect(firstSignal.aborted).toBe(true)
    first.close()
    await act(async () => {
      await firstSend
    })

    let secondSend!: Promise<void>
    await act(async () => {
      secondSend = result.current.send('build another skill', 'openai-prod')
      await wait(10)
    })

    expect(apiStreamMock).toHaveBeenCalledTimes(2)
    const secondSignal = apiStreamMock.mock.calls[1][2]?.signal as AbortSignal
    expect(apiStreamMock.mock.calls[1][2]).toMatchObject(managedOptions())
    expect(secondSignal.aborted).toBe(false)

    second.close()
    await act(async () => {
      await secondSend
    })
  })

  it('aborts the current authoring stream when the hook unmounts', async () => {
    const stream = controllableStreamResponse()
    apiStreamMock.mockResolvedValueOnce(stream.response)

    const { result, unmount } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    let send!: Promise<void>
    await act(async () => {
      send = result.current.send('build a skill', 'openai-prod')
      await wait(10)
    })

    const signal = apiStreamMock.mock.calls[0][2]?.signal as AbortSignal
    expect(apiStreamMock.mock.calls[0][2]).toMatchObject(managedOptions())
    expect(signal.aborted).toBe(false)

    unmount()

    expect(signal.aborted).toBe(true)

    stream.close()
    await act(async () => {
      await send
    })
  })

  it('does not apply late draft patches from the previous managed project', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const stream = controllableStreamResponse()
    apiStreamMock.mockResolvedValueOnce(stream.response)

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    let send!: Promise<void>
    await act(async () => {
      send = result.current.send('build a project-a skill', 'openai-prod')
      await wait(10)
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    await act(async () => {
      stream.enqueue({
        type: 'draft_patch',
        patch: {
          name: 'project-a-skill',
          content: 'project A only',
        },
      })
      stream.close()
      await send
    })

    expect(result.current.draft.name).toBe('')
    expect(result.current.draft.content).toBe('')
    expect(result.current.streaming).toBe(false)
  })

  it('applies a final draft patch when the stream closes without a trailing newline', async () => {
    apiStreamMock.mockResolvedValueOnce(
      streamResponseText(
        `data: ${JSON.stringify({
          type: 'draft_patch',
          patch: {
            name: 'final-skill',
            content: 'from terminal frame',
          },
        })}`,
      ),
    )

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      await result.current.send('build a skill', 'openai-prod')
    })

    expect(result.current.draft.name).toBe('final-skill')
    expect(result.current.draft.content).toBe('from terminal frame')
  })

  it('does not attach a saved draft id after switching managed project', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const save = deferred<{ skill_id: SkillId }>()
    managedPostMock.mockReturnValueOnce(save.promise)

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({ ...prev, name: 'project-a-skill' }))
      await wait(0)
    })

    let saveResult!: Promise<SkillId | null>
    await act(async () => {
      saveResult = result.current.saveDraft()
      await wait(0)
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await wait(0)
    })

    await act(async () => {
      save.resolve({ skill_id: PROJECT_SKILL_ID })
      await saveResult
    })

    await expect(saveResult).resolves.toBeNull()
    expect(result.current.draftSkillId).toBeNull()
    expect(result.current.saveError).toBeNull()
  })

  it('does not attach a saved draft id after the hook unmounts', async () => {
    const save = deferred<{ skill_id: SkillId }>()
    managedPostMock.mockReturnValueOnce(save.promise)

    const { result, unmount } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({ ...prev, name: 'unmounted-skill' }))
      await wait(0)
    })

    let saveResult!: Promise<SkillId | null>
    await act(async () => {
      saveResult = result.current.saveDraft()
      await wait(0)
    })

    unmount()

    await act(async () => {
      save.resolve({ skill_id: UNMOUNTED_SKILL_ID })
      await saveResult
    })

    await expect(saveResult).resolves.toBeNull()
  })

  it('does not attach a saved draft id when save resolves in the same turn as a project switch', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })
    const save = deferred<{ skill_id: SkillId }>()
    managedPostMock.mockReturnValueOnce(save.promise)

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({ ...prev, name: 'project-a-skill' }))
      await wait(0)
    })

    let saveResult!: Promise<SkillId | null>
    await act(async () => {
      saveResult = result.current.saveDraft()
      await wait(0)
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      save.resolve({ skill_id: PROJECT_SKILL_ID })
      await saveResult
      await Promise.resolve()
    })

    await expect(saveResult).resolves.toBeNull()
    expect(result.current.draftSkillId).toBeNull()
    expect(result.current.saveError).toBeNull()
  })

  it('does not save a draft from an old authoring workspace after the managed project changes in the same tick', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({
        ...prev,
        name: 'project-a authoring draft',
        description: 'draft for project A only',
        content: '# Project A Skill',
      }))
      await wait(0)
    })

    let saveResult!: Promise<string | null>
    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      saveResult = result.current.saveDraft()
      await saveResult
    })

    await expect(saveResult).resolves.toBeNull()
    expect(managedPostMock).not.toHaveBeenCalledWith(
      'skills/ai-authoring/save-draft',
      expect.anything(),
      managedOptions(),
    )
  })

  it('does not start an authoring stream from an old workspace after the managed project changes in the same tick', async () => {
    useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-a' })

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    let send!: Promise<void>
    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      send = result.current.send('build project A deployment skill', 'openai-prod')
      await send
    })

    expect(apiStreamMock).not.toHaveBeenCalled()
    expect(result.current.messages).toEqual([])
  })

  it('does not start authoring writes when the current project is archived', async () => {
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo('2026-01-02T00:00:00Z'),
    })

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({
        ...prev,
        name: 'archived project draft',
        content: '# Archived project draft',
      }))
      await wait(0)
    })

    let send!: Promise<void>
    let save!: Promise<string | null>
    let scan!: Promise<void>
    let publish!: Promise<{ skillId: SkillId | null; error?: string }>

    await act(async () => {
      send = result.current.send('build archived project skill', 'openai-prod')
      save = result.current.saveDraft()
      scan = result.current.runScan()
      publish = result.current.publish()
      await send
      await save
      await scan
      await publish
    })

    expect(apiStreamMock).not.toHaveBeenCalled()
    expect(managedPostMock).not.toHaveBeenCalled()
    await expect(save).resolves.toBeNull()
    await expect(publish).resolves.toEqual({ skillId: null, error: '发布已取消' })
  })

  it('aborts and ignores an in-flight authoring stream after the current project is archived', async () => {
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo(null),
    })
    const stream = controllableStreamResponse()
    apiStreamMock.mockResolvedValueOnce(stream.response)

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    let send!: Promise<void>
    await act(async () => {
      send = result.current.send('build a project skill', 'openai-prod')
      await wait(10)
    })

    const signal = apiStreamMock.mock.calls[0][2]?.signal as AbortSignal
    expect(apiStreamMock.mock.calls[0][2]).toMatchObject(managedOptions())
    expect(signal.aborted).toBe(false)

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      await wait(0)
    })

    expect(signal.aborted).toBe(true)
    expect(result.current.streaming).toBe(false)

    await act(async () => {
      stream.enqueue({
        type: 'draft_patch',
        patch: {
          name: 'should-not-apply',
          content: 'late archived project patch',
        },
      })
      stream.close()
      await send
    })

    expect(result.current.draft.name).toBe('')
    expect(result.current.draft.content).toBe('')
  })

  it('does not keep polling a security scan after the hook unmounts', async () => {
    vi.useFakeTimers()
    managedPostMock
      .mockResolvedValueOnce({ skill_id: SCAN_SKILL_ID })
      .mockResolvedValueOnce(scanResponse('scanning'))
    managedGetMock.mockResolvedValue(scanResponse('passed'))

    const { result, unmount } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({ ...prev, name: 'scan target' }))
      await Promise.resolve()
    })

    let scan!: Promise<void>
    await act(async () => {
      scan = result.current.runScan()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(2)

    unmount()

    await act(async () => {
      vi.advanceTimersByTime(3000)
      await Promise.resolve()
      await scan
    })

    expect(managedGetMock).not.toHaveBeenCalled()
  })

  it('does not continue publishing lifecycle transitions after the hook unmounts', async () => {
    const submitReview = deferred<Record<string, never>>()
    managedPostMock
      .mockResolvedValueOnce({ skill_id: PUBLISH_SKILL_ID })
      .mockReturnValueOnce(submitReview.promise)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})

    const { result, unmount } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({ ...prev, name: 'publish target' }))
      await wait(0)
    })

    let publish!: Promise<{ skillId: SkillId | null; error?: string }>
    await act(async () => {
      publish = result.current.publish()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(2)

    unmount()

    await act(async () => {
      submitReview.resolve({})
      await publish
    })

    expect(managedPostMock).toHaveBeenCalledTimes(2)
    await expect(publish).resolves.toEqual({ skillId: null, error: '发布已取消' })
  })

  it('does not approve or publish a version after submit-review fails', async () => {
    managedPostMock
      .mockResolvedValueOnce({ skill_id: BLOCKED_SKILL_ID })
      .mockRejectedValueOnce(new ApiError('SKILL_SECURITY_BLOCKED'))

    const { result } = renderHook(() => useSkillAuthoring({ startFresh: true }))

    await act(async () => {
      result.current.setDraft((prev) => ({ ...prev, name: 'blocked publish target' }))
      await wait(0)
    })

    let publish!: Promise<{ skillId: SkillId | null; error?: string }>
    await act(async () => {
      publish = result.current.publish()
      await publish
    })

    expect(managedPostMock).toHaveBeenCalledTimes(2)
    expect(managedPostMock).toHaveBeenNthCalledWith(
      1,
      'skills/ai-authoring/save-draft',
      expect.anything(),
      managedOptions(),
    )
    expect(managedPostMock).toHaveBeenNthCalledWith(
      2,
      `/skills/${BLOCKED_SKILL_ID}/submit-review`,
      {},
      managedOptions(),
    )
    expect(managedPostMock).not.toHaveBeenCalledWith(
      `/skills/${BLOCKED_SKILL_ID}/approve`,
      {},
      managedOptions(),
    )
    expect(managedPostMock).not.toHaveBeenCalledWith(
      `/skills/${BLOCKED_SKILL_ID}/versions`,
      {
        release_notes: null,
      },
      managedOptions(),
    )
    await expect(publish).resolves.toMatchObject({
      skillId: BLOCKED_SKILL_ID,
      error: expect.any(String),
    })
  })
})

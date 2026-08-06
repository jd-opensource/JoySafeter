/**
 * AI-assisted skill authoring hook.
 *
 * Owns the workspace state (conversation + draft + scan result) and the
 * three side-effecting actions the workspace exposes:
 *   - send(text)        — append user turn, stream the LLM response, fold
 *                          text_delta into the trailing assistant message
 *                          and draft_patch into the right-side preview
 *   - saveDraft()       — POST /skills/ai-authoring/save-draft, store the
 *                          returned skill_id so subsequent saves update in
 *                          place. Idempotent.
 *   - runScan()         — POST /skills/{id}/security-scans/rescan (async
 *                          dispatch path) + start polling latest verdict.
 *
 * Persists state to localStorage on every change so the workspace survives
 * reloads / device switches.
 *
 * Mirrors the SSE consumption pattern from use-quickstart-chat.ts (same
 * fetch + getReader + line-by-line parse loop). Managed scope is captured
 * once per render and passed explicitly with every request.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { apiStream, ApiError, managedGet, managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { getOperationErrorMessageWithDetails } from '@/lib/managed/errors'
import {
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { getManagedStreamErrorMessage } from '@/lib/managed/stream-errors'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

const STORAGE_KEY_PREFIX = 'joysafeter:skill-authoring-state:v2'

const passthroughTranslator = (key: string) => key

export type AuthoringMessage = {
  role: 'user' | 'assistant'
  content: string
}

export type SkillDraftFile = {
  path: string
  content: string
}

export type SkillDraft = {
  name: string
  description: string
  tags: string[]
  content: string
  files: SkillDraftFile[]
}

const EMPTY_DRAFT: SkillDraft = {
  name: '',
  description: '',
  tags: [],
  content: '',
  files: [],
}

type PersistedState = {
  messages: AuthoringMessage[]
  draft: SkillDraft
  draftSkillId: string | null
}

type SaveDraftResponse = { skill_id?: string; created?: boolean; error?: string; code?: string }

type ScanRecord = {
  id?: string
  status?: string
  severity?: string | null
  score?: number | null
  issues_count?: number
  error_message?: string | null
  scanned_at?: string | null
}

function getStorageKey(scope: string): string {
  return `${STORAGE_KEY_PREFIX}:${scope || 'no-managed-context'}`
}

function loadPersisted(storageKey: string): Partial<PersistedState> | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed as PersistedState
  } catch {
    return null
  }
}

function getCurrentManagedScope() {
  const { currentOrgId, currentProjectId } = useProjectStore.getState()
  return managedScopeKey(currentOrgId, currentProjectId)
}

function getInitialState(startFresh: boolean, storageKey: string): PersistedState {
  if (startFresh) {
    return { messages: [], draft: EMPTY_DRAFT, draftSkillId: null }
  }
  const saved = loadPersisted(storageKey)
  return {
    messages: Array.isArray(saved?.messages) ? saved.messages : [],
    draft: saved?.draft ? { ...EMPTY_DRAFT, ...saved.draft } : EMPTY_DRAFT,
    draftSkillId: saved?.draftSkillId || null,
  }
}

export function useSkillAuthoring(options?: { startFresh?: boolean }) {
  const startFresh = options?.startFresh ?? false
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const managedScopeKeyValue = managedScope.key
  const storageKey = getStorageKey(managedScopeKeyValue)
  const [initialState] = useState(() => getInitialState(startFresh, storageKey))
  const [messages, setMessages] = useState<AuthoringMessage[]>(initialState.messages)
  const [draft, setDraft] = useState<SkillDraft>(initialState.draft)
  const [draftSkillId, setDraftSkillId] = useState<string | null>(initialState.draftSkillId)
  const [streaming, setStreaming] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [scanRunning, setScanRunning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanRecord | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [hydrated] = useState(true)
  const abortRef = useRef<AbortController | null>(null)
  const streamInFlightRef = useRef(false)
  const managedScopeRef = useRef(managedScopeKeyValue)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const storageKeyRef = useRef(storageKey)
  const lifecycleRunRef = useRef(0)
  const isCurrentManagedScope = useCallback(
    (scope: string) => managedScopeRef.current === scope && getCurrentManagedScope() === scope,
    [],
  )
  const isCurrentWritableManagedScope = useCallback(
    (scope: string) => isCurrentManagedScope(scope) && currentProjectAllowsWrite(),
    [isCurrentManagedScope],
  )
  const isCurrentLifecycleRun = useCallback(
    (scope: string, lifecycleRun: number) =>
      isCurrentWritableManagedScope(scope) && lifecycleRunRef.current === lifecycleRun,
    [isCurrentWritableManagedScope],
  )
  // Ref-mirror of draft so the streaming handler always reads fresh state
  // even when React hasn't flushed the most recent setDraft yet (the SSE
  // loop applies many patches per second).
  const draftRef = useRef<SkillDraft>(EMPTY_DRAFT)
  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  useEffect(
    () => () => {
      lifecycleRunRef.current += 1
      abortRef.current?.abort()
      abortRef.current = null
      streamInFlightRef.current = false
    },
    [],
  )

  useEffect(() => {
    if (!projectReadOnly) return
    lifecycleRunRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    streamInFlightRef.current = false
    setStreaming(false)
    setScanRunning(false)
    setPublishing(false)
  }, [projectReadOnly])

  // A fresh session (?new=1 in the URL) wipes the saved blob so a subsequent
  // refresh genuinely shows an empty workspace.
  useEffect(() => {
    if (startFresh) {
      if (typeof window !== 'undefined') {
        try {
          window.localStorage.removeItem(storageKeyRef.current)
        } catch {
          /* noop */
        }
      }
    }
  }, [startFresh])

  useEffect(() => {
    if (managedScopeRef.current === managedScopeKeyValue) return

    lifecycleRunRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    streamInFlightRef.current = false
    managedScopeRef.current = managedScopeKeyValue
    managedRequestScopeRef.current = managedScope
    storageKeyRef.current = storageKey

    const next = getInitialState(false, storageKey)
    draftRef.current = next.draft
    setMessages(next.messages)
    setDraft(next.draft)
    setDraftSkillId(next.draftSkillId)
    setStreaming(false)
    setSaveError(null)
    setScanRunning(false)
    setScanResult(null)
    setPublishing(false)
  }, [managedScopeKeyValue, storageKey])

  // Mirror state into localStorage. Skipped until after hydration so we
  // don't immediately overwrite the saved blob with our empty defaults.
  useEffect(() => {
    if (!hydrated || typeof window === 'undefined') return
    if (managedScopeRef.current !== managedScopeKeyValue) return
    try {
      const payload: PersistedState = { messages, draft, draftSkillId }
      window.localStorage.setItem(storageKey, JSON.stringify(payload))
    } catch {
      // Quota exceeded etc. — drop silently; the workspace still works
      // in-memory, just without resume-across-reload.
    }
  }, [messages, draft, draftSkillId, hydrated, managedScopeKeyValue, storageKey])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    streamInFlightRef.current = false
    setStreaming(false)
    setMessages([])
    setDraft(EMPTY_DRAFT)
    setDraftSkillId(null)
    setScanResult(null)
    setSaveError(null)
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.removeItem(storageKeyRef.current)
      } catch {
        /* noop */
      }
    }
  }, [])

  const send = useCallback(
    async (userText: string, secretRef: string) => {
      const trimmed = userText.trim()
      if (!trimmed || streamInFlightRef.current) return
      if (!secretRef) {
        setMessages((prev) => [
          ...prev,
          { role: 'user', content: trimmed },
          {
            role: 'assistant',
            content: '⚠️ 请先在右上角选择一个包含 OPENAI_API_KEY 的密钥(Secret),才能让我开始创作。',
          },
        ])
        return
      }

      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return

      // Append the user turn + a blank assistant placeholder we'll fold
      // streaming text into.
      const nextMessages: AuthoringMessage[] = [
        ...messages,
        { role: 'user', content: trimmed },
        { role: 'assistant', content: '' },
      ]
      setMessages(nextMessages)
      streamInFlightRef.current = true
      setStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const resp = await apiStream(
          'skills/ai-authoring/chat',
          {
            secret_ref: secretRef,
            // Send the conversation up to (but not including) the blank
            // assistant placeholder we just appended.
            messages: nextMessages.slice(0, -1),
            draft: draftRef.current,
          },
          { ...managedRequestOptions(requestScope), signal: controller.signal },
        )

        const reader = resp.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let assistantAccum = ''
        let sawPatch = false

        const processLine = (line: string) => {
          if (!line.startsWith('data:')) return
          const raw = line.slice(5).trim()
          if (!raw || raw === '[DONE]') return
          let evt: { type?: string; [k: string]: unknown }
          try {
            evt = JSON.parse(raw)
          } catch {
            return
          }
          if (!isCurrentWritableManagedScope(scopeAtStart)) return
          switch (evt.type) {
            case 'text_delta':
              assistantAccum += (evt.text as string) || ''
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: assistantAccum }
                }
                return updated
              })
              break
            case 'draft_patch': {
              const patch = (evt.patch as Partial<SkillDraft>) || {}
              setDraft((prev) => ({ ...prev, ...patch }))
              sawPatch = true
              break
            }
            case 'error':
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                const msg = getManagedStreamErrorMessage((key) => key, evt, 'LLM 调用失败')
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: `${last.content || ''}\n\n⚠️ ${msg}`,
                  }
                }
                return updated
              })
              break
            case 'done':
              // server closes after this; outer loop exits on stream end
              break
          }
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            if (buffer.trim()) {
              processLine(buffer)
              buffer = ''
            }
            break
          }
          if (!isCurrentWritableManagedScope(scopeAtStart)) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            processLine(line)
          }
        }

        // If the LLM only patched the right-side draft and didn't say
        // anything in chat, leave a helpful summary so the assistant bubble
        // isn't blank. Otherwise the user sees an empty "..." with no idea
        // anything happened.
        if (!assistantAccum && sawPatch) {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: '✓ 已更新右侧草稿。你可以继续告诉我要怎么改,或直接在右侧编辑。',
              }
            }
            return updated
          })
        } else if (!assistantAccum && !sawPatch) {
          // Stream ended but the model said nothing and patched nothing.
          // Surface it so the user can retry rather than stare at "...".
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: '⚠️ AI 没有返回内容,请换种说法再试一次。',
              }
            }
            return updated
          })
        }
      } catch (err) {
        if ((err as { name?: string })?.name === 'AbortError') {
          // user cancelled — keep partial state
          return
        }
        if (!isCurrentWritableManagedScope(scopeAtStart) || abortRef.current !== controller) return
        const message = err instanceof Error ? err.message : '连接失败,请稍后重试。'
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last && last.role === 'assistant') {
            updated[updated.length - 1] = {
              ...last,
              content: `${last.content || ''}\n\n⚠️ ${message}`,
            }
          }
          return updated
        })
      } finally {
        if (abortRef.current === controller && isCurrentWritableManagedScope(scopeAtStart)) {
          streamInFlightRef.current = false
          abortRef.current = null
          setStreaming(false)
        }
      }
    },
    [isCurrentWritableManagedScope, messages],
  )

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    streamInFlightRef.current = false
    setStreaming(false)
  }, [])

  const saveDraft = useCallback(async (): Promise<string | null> => {
    setSaveError(null)
    const current = draftRef.current
    if (!current.name.trim()) {
      setSaveError('请先填写技能名称才能保存草稿。')
      return null
    }
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    const lifecycleRunAtStart = lifecycleRunRef.current
    if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return null
    try {
      const data = await managedPost<SaveDraftResponse>(
        'skills/ai-authoring/save-draft',
        {
          draft_skill_id: draftSkillId,
          name: current.name,
          description: current.description,
          content: current.content,
          tags: current.tags,
          files: current.files,
        },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return null
      if (data.error || !data.skill_id) {
        setSaveError(data.error || '保存失败: 响应缺少 skill_id')
        return null
      }
      setDraftSkillId(data.skill_id)
      return data.skill_id
    } catch (err) {
      if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return null
      setSaveError(
        `保存失败:${getOperationErrorMessageWithDetails(passthroughTranslator, err, '保存失败')}`,
      )
      return null
    }
  }, [draftSkillId, isCurrentLifecycleRun])

  const fetchLatestScan = useCallback(
    async (skillId: string, requestScope: ManagedRequestScope): Promise<ScanRecord | null> => {
      return await managedGet<ScanRecord>(
        apiResourcePath('skills', skillId, 'security-scans', 'latest'),
        managedRequestOptions(requestScope),
      )
    },
    [],
  )

  const runScan = useCallback(async () => {
    // Need a draft row on the server first — scan operates on a real
    // skill_id. Auto-save before scanning if necessary.
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    const lifecycleRunAtStart = lifecycleRunRef.current
    if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
    let sid = draftSkillId
    if (!sid) {
      sid = await saveDraft()
      if (!sid || !isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
    }
    setScanRunning(true)
    setScanResult(null)
    try {
      const initialScan = await managedPost<ScanRecord>(
        apiResourcePath('skills', sid, 'security-scans', 'rescan'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
      setScanResult(initialScan)
      // Backend dispatched async; poll latest until status leaves 'scanning'.
      // Cap polling at 120s so a stuck scan doesn't pin the UI forever.
      const deadline = Date.now() + 120_000
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 3000))
        if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
        const latest = await fetchLatestScan(sid, requestScope)
        if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
        if (!latest) continue
        if (latest.status && latest.status !== 'scanning') {
          setScanResult(latest)
          return
        }
      }
      if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
      setScanResult({ status: 'timeout' })
    } catch (error) {
      if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
      setScanResult({
        status: 'failed',
        error_message: getOperationErrorMessageWithDetails(
          passthroughTranslator,
          error,
          '安全扫描失败',
        ),
      })
    } finally {
      if (isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) {
        setScanRunning(false)
      }
    }
  }, [draftSkillId, saveDraft, fetchLatestScan, isCurrentLifecycleRun])

  // Publish the draft as a usable skill. Agents can only reference *published*
  // versions, so "create a skill" really means: save → submit for review →
  // approve → cut version 1.0.0. Runs the lifecycle transitions in sequence;
  // any already-satisfied transition (e.g. re-publishing) is treated as a
  // no-op rather than a hard error. Returns the skill id on success.
  const publish = useCallback(async (): Promise<{ skillId: string | null; error?: string }> => {
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    const lifecycleRunAtStart = lifecycleRunRef.current
    const isCurrentPublish = () => isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)
    const sid = await saveDraft()
    if (!isCurrentPublish()) {
      return { skillId: null, error: '发布已取消' }
    }
    if (!sid) {
      return { skillId: null, error: saveError || '保存失败' }
    }
    // Fire one lifecycle transition; tolerate "invalid transition" (the skill
    // is already past this state) so re-publishing an approved skill still
    // reaches the version-publish step.
    const transition = async (
      endpoint: string,
      fallbackMessage: string,
    ): Promise<{ ok: true } | { ok: false; error: string }> => {
      if (!isCurrentPublish()) return { ok: false, error: '发布已取消' }
      try {
        await managedPost(
          apiResourcePath('skills', sid, endpoint),
          {},
          managedRequestOptions(requestScope),
        )
        if (!isCurrentPublish()) return { ok: false, error: '发布已取消' }
        return { ok: true }
      } catch (error) {
        if (!isCurrentPublish()) return { ok: false, error: '发布已取消' }
        // Already in/past the target state — not a real failure.
        if (error instanceof ApiError && error.code === 'SKILL_LIFECYCLE_INVALID_TRANSITION') {
          return { ok: true }
        }
        return {
          ok: false,
          error: getOperationErrorMessageWithDetails(passthroughTranslator, error, fallbackMessage),
        }
      }
    }

    setPublishing(true)
    try {
      // draft → pending_review → approved. Both tolerate "already there".
      const submit = await transition('submit-review', '提交审核失败')
      if (!isCurrentPublish()) return { skillId: null, error: '发布已取消' }
      if (!submit.ok) return { skillId: sid, error: submit.error }

      const approve = await transition('approve', '审核通过失败')
      if (!isCurrentPublish()) return { skillId: null, error: '发布已取消' }
      if (!approve.ok) return { skillId: sid, error: approve.error }

      // Cut the first published version. Empty version lets the backend
      // auto-assign (0.1.0 for the first release / bumped patch otherwise).
      try {
        if (!isCurrentPublish()) return { skillId: null, error: '发布已取消' }
        await managedPost(
          apiResourcePath('skills', sid, 'versions'),
          { release_notes: null },
          managedRequestOptions(requestScope),
        )
        if (!isCurrentPublish()) return { skillId: null, error: '发布已取消' }
      } catch (error) {
        if (!isCurrentPublish()) return { skillId: null, error: '发布已取消' }
        return {
          skillId: sid,
          error: getOperationErrorMessageWithDetails(passthroughTranslator, error, '发布版本失败'),
        }
      }
      return { skillId: sid }
    } finally {
      if (isCurrentPublish()) {
        setPublishing(false)
      }
    }
  }, [isCurrentLifecycleRun, saveDraft, saveError])

  return {
    // state
    messages,
    draft,
    draftSkillId,
    streaming,
    saveError,
    scanRunning,
    scanResult,
    publishing,
    hydrated,
    // mutations
    setDraft,
    send,
    cancel,
    saveDraft,
    runScan,
    publish,
    reset,
  }
}

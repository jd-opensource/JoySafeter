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
 * fetch + getReader + line-by-line parse loop). Auth headers built the
 * same way (CSRF + X-Org-Id + X-Project-Id from the project store).
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { MANAGED_API_BASE } from '@/lib/api-client'
import { getCsrfToken } from '@/lib/auth/csrf'
import { useProjectStore } from '@/stores/managed/project-store'

const STORAGE_KEY = 'joysafeter:skill-authoring-state:v1'

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
  visibility: 'private' | 'project' | 'organization' | 'public' | null
  content: string
  files: SkillDraftFile[]
}

const EMPTY_DRAFT: SkillDraft = {
  name: '',
  description: '',
  tags: [],
  visibility: null,
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
  scanned_at?: string | null
}

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const csrf = getCsrfToken()
  if (csrf) headers['X-CSRF-Token'] = csrf
  const { currentProjectId, currentOrgId } = useProjectStore.getState()
  if (currentOrgId) headers['X-Org-Id'] = currentOrgId
  if (currentProjectId) headers['X-Project-Id'] = currentProjectId
  return headers
}

function loadPersisted(): Partial<PersistedState> | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed as PersistedState
  } catch {
    return null
  }
}

function stripSkillIdPrefix(id: string): string {
  return id.startsWith('skill_') ? id.slice('skill_'.length) : id
}

export function useSkillAuthoring(options?: { startFresh?: boolean }) {
  const startFresh = options?.startFresh ?? false
  const [messages, setMessages] = useState<AuthoringMessage[]>([])
  const [draft, setDraft] = useState<SkillDraft>(EMPTY_DRAFT)
  const [draftSkillId, setDraftSkillId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [scanRunning, setScanRunning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanRecord | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [hydrated, setHydrated] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  // Ref-mirror of draft so the streaming handler always reads fresh state
  // even when React hasn't flushed the most recent setDraft yet (the SSE
  // loop applies many patches per second).
  const draftRef = useRef<SkillDraft>(EMPTY_DRAFT)
  draftRef.current = draft

  // Restore from localStorage on first mount, UNLESS the caller asked for
  // a fresh session (?new=1 in the URL — set when the user clicks the
  // "AI 创作" entry on the list page). A fresh start also wipes the saved
  // blob so a subsequent refresh genuinely shows an empty workspace.
  useEffect(() => {
    if (startFresh) {
      if (typeof window !== 'undefined') {
        try {
          window.localStorage.removeItem(STORAGE_KEY)
        } catch {
          /* noop */
        }
      }
      setHydrated(true)
      return
    }
    const saved = loadPersisted()
    if (saved) {
      if (Array.isArray(saved.messages)) setMessages(saved.messages)
      if (saved.draft) setDraft({ ...EMPTY_DRAFT, ...saved.draft })
      if (saved.draftSkillId) setDraftSkillId(saved.draftSkillId)
    }
    setHydrated(true)
  }, [startFresh])

  // Mirror state into localStorage. Skipped until after hydration so we
  // don't immediately overwrite the saved blob with our empty defaults.
  useEffect(() => {
    if (!hydrated || typeof window === 'undefined') return
    try {
      const payload: PersistedState = { messages, draft, draftSkillId }
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch {
      // Quota exceeded etc. — drop silently; the workspace still works
      // in-memory, just without resume-across-reload.
    }
  }, [messages, draft, draftSkillId, hydrated])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setDraft(EMPTY_DRAFT)
    setDraftSkillId(null)
    setScanResult(null)
    setSaveError(null)
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.removeItem(STORAGE_KEY)
      } catch {
        /* noop */
      }
    }
  }, [])

  const send = useCallback(
    async (userText: string, secretRef: string) => {
      const trimmed = userText.trim()
      if (!trimmed) return
      if (!secretRef) {
        setMessages((prev) => [
          ...prev,
          { role: 'user', content: trimmed },
          {
            role: 'assistant',
            content:
              '⚠️ 请先在右上角选择一个包含 OPENAI_API_KEY 的密钥(Secret),才能让我开始创作。',
          },
        ])
        return
      }

      // Append the user turn + a blank assistant placeholder we'll fold
      // streaming text into.
      const nextMessages: AuthoringMessage[] = [
        ...messages,
        { role: 'user', content: trimmed },
        { role: 'assistant', content: '' },
      ]
      setMessages(nextMessages)
      setStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const resp = await fetch(`${MANAGED_API_BASE}/skills/ai-authoring/chat`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({
            secret_ref: secretRef,
            // Send the conversation up to (but not including) the blank
            // assistant placeholder we just appended.
            messages: nextMessages.slice(0, -1),
            draft: draftRef.current,
          }),
          signal: controller.signal,
        })

        if (!resp.ok) {
          let detail = `HTTP ${resp.status}`
          try {
            const err = await resp.json()
            if (err?.detail) detail = String(err.detail)
          } catch {
            /* keep raw status */
          }
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: `⚠️ ${detail}`,
              }
            }
            return updated
          })
          return
        }

        const reader = resp.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let assistantAccum = ''
        let sawPatch = false

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const raw = line.slice(5).trim()
            if (!raw || raw === '[DONE]') continue
            let evt: { type?: string; [k: string]: unknown }
            try {
              evt = JSON.parse(raw)
            } catch {
              continue
            }
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
                  const msg = (evt.message as string) || 'LLM 调用失败'
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
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last && last.role === 'assistant') {
            updated[updated.length - 1] = {
              ...last,
              content: `${last.content || ''}\n\n⚠️ 连接失败,请稍后重试。`,
            }
          }
          return updated
        })
      } finally {
        setStreaming(false)
        abortRef.current = null
      }
    },
    [messages],
  )

  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const saveDraft = useCallback(async (): Promise<string | null> => {
    setSaveError(null)
    const current = draftRef.current
    if (!current.name.trim()) {
      setSaveError('请先填写技能名称才能保存草稿。')
      return null
    }
    try {
      const resp = await fetch(`${MANAGED_API_BASE}/skills/ai-authoring/save-draft`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          draft_skill_id: draftSkillId,
          name: current.name,
          description: current.description,
          content: current.content,
          tags: current.tags,
          visibility: current.visibility,
          files: current.files,
        }),
      })
      const data: SaveDraftResponse = await resp.json().catch(() => ({}))
      if (!resp.ok || data.error || !data.skill_id) {
        setSaveError(data.error || `保存失败 (HTTP ${resp.status})`)
        return null
      }
      setDraftSkillId(data.skill_id)
      return data.skill_id
    } catch (err) {
      setSaveError(`保存失败:${(err as Error).message}`)
      return null
    }
  }, [draftSkillId])

  const fetchLatestScan = useCallback(async (skillId: string): Promise<ScanRecord | null> => {
    const sid = stripSkillIdPrefix(skillId)
    try {
      const resp = await fetch(
        `${MANAGED_API_BASE}/skills/${sid}/security-scans/latest`,
        {
          credentials: 'include',
          headers: getAuthHeaders(),
        },
      )
      if (!resp.ok) return null
      return (await resp.json()) as ScanRecord
    } catch {
      return null
    }
  }, [])

  const runScan = useCallback(async () => {
    // Need a draft row on the server first — scan operates on a real
    // skill_id. Auto-save before scanning if necessary.
    let sid = draftSkillId
    if (!sid) {
      sid = await saveDraft()
      if (!sid) return
    }
    setScanRunning(true)
    setScanResult(null)
    const justId = stripSkillIdPrefix(sid)
    try {
      const resp = await fetch(
        `${MANAGED_API_BASE}/skills/${justId}/security-scans/rescan`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({}),
        },
      )
      if (!resp.ok) {
        setScanResult({ status: 'failed' })
        return
      }
      // Backend dispatched async; poll latest until status leaves 'scanning'.
      // Cap polling at 120s so a stuck scan doesn't pin the UI forever.
      const deadline = Date.now() + 120_000
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 3000))
        const latest = await fetchLatestScan(sid)
        if (!latest) continue
        if (latest.status && latest.status !== 'scanning') {
          setScanResult(latest)
          return
        }
      }
      setScanResult({ status: 'timeout' })
    } finally {
      setScanRunning(false)
    }
  }, [draftSkillId, saveDraft, fetchLatestScan])

  // Publish the draft as a usable skill. Agents can only reference *published*
  // versions, so "create a skill" really means: save → submit for review →
  // approve → cut version 1.0.0. Runs the lifecycle transitions in sequence;
  // any already-satisfied transition (e.g. re-publishing) is treated as a
  // no-op rather than a hard error. Returns the skill id on success.
  const publish = useCallback(async (): Promise<{ skillId: string | null; error?: string }> => {
    const sid = await saveDraft()
    if (!sid) return { skillId: null, error: saveError || '保存失败' }
    const justId = stripSkillIdPrefix(sid)

    // Fire one lifecycle transition; tolerate "invalid transition" (the skill
    // is already past this state) so re-publishing an approved skill still
    // reaches the version-publish step.
    const transition = async (endpoint: string): Promise<boolean> => {
      try {
        const resp = await fetch(`${MANAGED_API_BASE}/skills/${justId}/${endpoint}`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({}),
        })
        if (resp.ok) return true
        const data = await resp.json().catch(() => ({}))
        // Already in/past the target state — not a real failure.
        if (data?.code === 'SKILL_LIFECYCLE_INVALID_TRANSITION') return true
        return false
      } catch {
        return false
      }
    }

    setPublishing(true)
    try {
      // draft → pending_review → approved. Both tolerate "already there".
      await transition('submit-review')
      await transition('approve')

      // Cut the first published version. Empty version lets the backend
      // auto-assign (0.1.0 for the first release / bumped patch otherwise).
      const verResp = await fetch(`${MANAGED_API_BASE}/skills/${justId}/versions`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ release_notes: null }),
      })
      if (!verResp.ok) {
        const data = await verResp.json().catch(() => ({}))
        return { skillId: sid, error: data?.detail || data?.error || `发布版本失败 (HTTP ${verResp.status})` }
      }
      return { skillId: sid }
    } finally {
      setPublishing(false)
    }
  }, [saveDraft, saveError])

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

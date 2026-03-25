/**
 * Hook encapsulating the full Skill Creator run lifecycle:
 * projection/reducer state, WS subscriptions, graph resolution,
 * history merging, and send/stop actions.
 */

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

import { findOrCreateGraphByTemplate } from '@/app/chat/services/utils/graphLookup'
import { formatToolDisplay } from '@/app/chat/shared/ToolCallDisplay'
import { generateId, type Message, type ToolCall } from '@/app/chat/types'
import { apiGet, API_ENDPOINTS } from '@/lib/api-client'
import { getChatWsClient } from '@/lib/ws/chat/chatWsClient'
import type { IncomingChatAcceptedEvent } from '@/lib/ws/chat/types'
import { getRunWsClient } from '@/lib/ws/runs/runWsClient'
import type { RunEventFrame, RunSnapshotFrame, RunStatusFrame } from '@/lib/ws/runs/types'
import { conversationService, type ConversationMessage } from '@/services/conversationService'
import { runService } from '@/services/runService'

import type { SkillPreviewData } from '@/app/skills/creator/page'

// ---------------------------------------------------------------------------
// Projection types & helpers
// ---------------------------------------------------------------------------

interface SkillCreatorRunProjection {
  version: number
  run_type: string
  status: string
  graph_id: string | null
  thread_id: string | null
  edit_skill_id: string | null
  messages: Array<Record<string, any>>
  current_assistant_message_id: string | null
  preview_data: Record<string, any> | string | null
  file_tree: Record<string, { action: string; size?: number; timestamp?: number }>
  interrupt: Record<string, any> | null
  meta: Record<string, any>
}

const EMPTY_PROJECTION: SkillCreatorRunProjection = {
  version: 1,
  run_type: 'skill_creator',
  status: 'idle',
  graph_id: null,
  thread_id: null,
  edit_skill_id: null,
  messages: [],
  current_assistant_message_id: null,
  preview_data: null,
  file_tree: {},
  interrupt: null,
  meta: {},
}

function cloneProjection(projection?: SkillCreatorRunProjection | null): SkillCreatorRunProjection {
  const source = projection || EMPTY_PROJECTION
  return {
    ...EMPTY_PROJECTION,
    ...source,
    messages: (source.messages || []).map((message) => ({
      ...message,
      tool_calls: Array.isArray(message.tool_calls)
        ? message.tool_calls.map((tool: Record<string, any>) => ({
            ...tool,
            args: tool?.args && typeof tool.args === 'object' ? { ...tool.args } : {},
          }))
        : [],
    })),
    file_tree: { ...(source.file_tree || {}) },
    meta: { ...(source.meta || {}) },
  }
}

function normalizeProjection(input?: Record<string, any> | null): SkillCreatorRunProjection {
  const candidate = input && typeof input === 'object' ? input : {}
  return cloneProjection({
    version: typeof candidate.version === 'number' ? candidate.version : 1,
    run_type: typeof candidate.run_type === 'string' ? candidate.run_type : 'skill_creator',
    status: typeof candidate.status === 'string' ? candidate.status : 'idle',
    graph_id: typeof candidate.graph_id === 'string' ? candidate.graph_id : null,
    thread_id: typeof candidate.thread_id === 'string' ? candidate.thread_id : null,
    edit_skill_id: typeof candidate.edit_skill_id === 'string' ? candidate.edit_skill_id : null,
    messages: Array.isArray(candidate.messages) ? candidate.messages : [],
    current_assistant_message_id:
      typeof candidate.current_assistant_message_id === 'string'
        ? candidate.current_assistant_message_id
        : null,
    preview_data:
      candidate.preview_data && typeof candidate.preview_data === 'object'
        ? candidate.preview_data
        : typeof candidate.preview_data === 'string'
          ? candidate.preview_data
          : null,
    file_tree:
      candidate.file_tree && typeof candidate.file_tree === 'object' ? candidate.file_tree : {},
    interrupt: candidate.interrupt && typeof candidate.interrupt === 'object' ? candidate.interrupt : null,
    meta: candidate.meta && typeof candidate.meta === 'object' ? candidate.meta : {},
  })
}

// ---------------------------------------------------------------------------
// Event reducer
// ---------------------------------------------------------------------------

function applySkillCreatorEvent(
  projection: SkillCreatorRunProjection,
  eventType: string,
  payload: Record<string, any>,
): SkillCreatorRunProjection {
  const next = cloneProjection(projection)

  if (eventType === 'run_initialized') {
    next.graph_id = typeof payload.graph_id === 'string' ? payload.graph_id : next.graph_id
    next.thread_id = typeof payload.thread_id === 'string' ? payload.thread_id : next.thread_id
    next.edit_skill_id =
      typeof payload.edit_skill_id === 'string' ? payload.edit_skill_id : next.edit_skill_id
    return next
  }

  if (eventType === 'user_message_added') {
    if (payload.message && typeof payload.message === 'object') {
      next.messages.push(payload.message)
    }
    return next
  }

  if (eventType === 'assistant_message_started') {
    if (payload.message && typeof payload.message === 'object') {
      next.messages.push(payload.message)
      next.current_assistant_message_id = String(payload.message.id || '')
    }
    return next
  }

  if (eventType === 'content_delta') {
    const messageId = String(payload.message_id || '')
    const delta = String(payload.delta || '')
    if (!messageId || !delta) return next
    next.messages = next.messages.map((message) =>
      String(message.id || '') === messageId
        ? { ...message, content: `${String(message.content || '')}${delta}` }
        : message,
    )
    return next
  }

  if (eventType === 'tool_start') {
    const messageId = String(payload.message_id || '')
    const tool = payload.tool
    if (!messageId || !tool || typeof tool !== 'object') return next
    next.messages = next.messages.map((message) => {
      if (String(message.id || '') !== messageId) return message
      const toolCalls = Array.isArray(message.tool_calls) ? [...message.tool_calls, tool] : [tool]
      return { ...message, tool_calls: toolCalls }
    })
    return next
  }

  if (eventType === 'tool_end') {
    const messageId = String(payload.message_id || '')
    const toolId = typeof payload.tool_id === 'string' ? payload.tool_id : null
    next.messages = next.messages.map((message) => {
      if (String(message.id || '') !== messageId) return message
      const toolCalls = Array.isArray(message.tool_calls) ? [...message.tool_calls] : []
      const targetIndex = toolId
        ? toolCalls.findIndex((tool) => String(tool?.id || '') === toolId)
        : toolCalls.findIndex((tool) => tool?.status === 'running')
      if (targetIndex < 0) return message
      toolCalls[targetIndex] = {
        ...toolCalls[targetIndex],
        status: 'completed',
        result: payload.tool_output,
        endTime: typeof payload.end_time === 'number' ? payload.end_time : toolCalls[targetIndex]?.endTime,
      }
      return { ...message, tool_calls: toolCalls }
    })
    if (payload.tool_name === 'preview_skill' && payload.tool_output != null) {
      next.preview_data =
        typeof payload.tool_output === 'object' || typeof payload.tool_output === 'string'
          ? payload.tool_output
          : next.preview_data
    }
    return next
  }

  if (eventType === 'file_event') {
    const path = typeof payload.path === 'string' ? payload.path : ''
    const action = typeof payload.action === 'string' ? payload.action : ''
    if (!path || !action) return next
    if (action === 'delete') {
      delete next.file_tree[path]
    } else {
      next.file_tree[path] = {
        action,
        size: typeof payload.size === 'number' ? payload.size : undefined,
        timestamp: typeof payload.timestamp === 'number' ? payload.timestamp : undefined,
      }
    }
    return next
  }

  if (eventType === 'interrupt') {
    next.interrupt = payload.interrupt && typeof payload.interrupt === 'object' ? payload.interrupt : null
    next.current_assistant_message_id = null
    return next
  }

  if (eventType === 'error') {
    next.meta = { ...next.meta, error: payload.message }
    return next
  }

  if (eventType === 'done') {
    next.meta = { ...next.meta, completed: true }
    next.current_assistant_message_id = null
    return next
  }

  if (eventType === 'status') {
    next.meta = { ...next.meta, status_message: payload.message }
    return next
  }

  return next
}

// ---------------------------------------------------------------------------
// Message mapping helpers
// ---------------------------------------------------------------------------

function normalizePreviewData(value: Record<string, any> | string | null): SkillPreviewData | null {
  if (!value) return null
  try {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value
    if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.files)) {
      return null
    }
    return parsed as SkillPreviewData
  } catch {
    return null
  }
}

function mapProjectionMessages(projection: SkillCreatorRunProjection): Message[] {
  const isStreamingRun = projection.status === 'queued' || projection.status === 'running'
  return projection.messages.map((message) => {
    const role =
      message.role === 'user' || message.role === 'assistant' || message.role === 'system'
        ? message.role
        : 'assistant'
    const toolCalls = Array.isArray(message.tool_calls)
      ? message.tool_calls.map((tool: Record<string, any>): ToolCall => {
          const rawName = String(tool?.name || 'tool')
          const rawArgs = tool?.args && typeof tool.args === 'object' ? tool.args : {}
          const { label, detail } = formatToolDisplay(rawName, rawArgs)
          const status =
            tool?.status === 'completed' || tool?.status === 'failed' ? tool.status : 'running'
          return {
            id: String(tool?.id || generateId()),
            name: label,
            args: {
              ...rawArgs,
              _detail: detail,
              _rawName: rawName,
            },
            status,
            result: tool?.result,
            startTime: typeof tool?.startTime === 'number' ? tool.startTime : Date.now(),
            endTime: typeof tool?.endTime === 'number' ? tool.endTime : undefined,
          }
        })
      : undefined

    return {
      id: String(message.id || generateId()),
      role,
      content: String(message.content || ''),
      timestamp: typeof message.timestamp === 'number' ? message.timestamp : Date.now(),
      tool_calls: toolCalls,
      isStreaming:
        projection.current_assistant_message_id === String(message.id || '') && isStreamingRun,
    }
  })
}

function mapConversationMessageToUi(message: ConversationMessage): Message {
  const metadata = message.metadata && typeof message.metadata === 'object' ? message.metadata : {}
  const toolCalls = Array.isArray(metadata.tool_calls)
    ? metadata.tool_calls.map((tool: Record<string, any>): ToolCall => {
        const rawName = String(tool?.name || 'tool')
        const rawArgs = tool?.arguments && typeof tool.arguments === 'object' ? tool.arguments : {}
        const { label, detail } = formatToolDisplay(rawName, rawArgs)
        const timestamp = new Date(message.created_at).getTime() || Date.now()
        return {
          id: String(tool?.id || generateId()),
          name: label,
          args: {
            ...rawArgs,
            _detail: detail,
            _rawName: rawName,
          },
          status: 'completed',
          startTime: timestamp,
          endTime: timestamp,
        }
      })
    : undefined

  return {
    id: `history-${message.id}`,
    role:
      message.role === 'user' || message.role === 'assistant' || message.role === 'system'
        ? message.role
        : 'assistant',
    content: String(message.content || ''),
    timestamp: new Date(message.created_at).getTime() || Date.now(),
    tool_calls: toolCalls,
  }
}

function areMessagesEquivalent(left: Message, right: Message): boolean {
  const leftToolNames = (left.tool_calls || []).map((tool) => tool.args?._rawName || tool.name).join('|')
  const rightToolNames = (right.tool_calls || []).map((tool) => tool.args?._rawName || tool.name).join('|')
  return left.role === right.role && left.content === right.content && leftToolNames === rightToolNames
}

function mergeHistoryWithRunMessages(historyMessages: Message[], runMessages: Message[]): Message[] {
  if (!historyMessages.length) return runMessages
  if (!runMessages.length) return historyMessages

  let overlap = 0
  const maxOverlap = Math.min(historyMessages.length, runMessages.length)
  for (let size = maxOverlap; size > 0; size -= 1) {
    let matched = true
    for (let index = 0; index < size; index += 1) {
      if (!areMessagesEquivalent(historyMessages[historyMessages.length - size + index], runMessages[index])) {
        matched = false
        break
      }
    }
    if (matched) {
      overlap = size
      break
    }
  }

  return [...historyMessages, ...runMessages.slice(overlap)]
}

function buildSkillCreatorUrl(runId: string, editSkillId: string | null): string {
  const params = new URLSearchParams()
  params.set('run', runId)
  if (editSkillId) {
    params.set('edit', editSkillId)
  }
  return `/skills/creator?${params.toString()}`
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseSkillCreatorRunReturn {
  messages: Message[]
  isProcessing: boolean
  isSubmitting: boolean
  threadId: string | null
  previewData: SkillPreviewData | null
  fileTree: Record<string, { action: string; size?: number; timestamp?: number }>
  graphReady: boolean
  graphError: string | null
  effectiveEditSkillId: string | null
  hasRunState: boolean
  showSaveDialog: boolean
  setShowSaveDialog: (open: boolean) => void
  sendMessage: (userPrompt: string) => Promise<boolean>
  stopMessage: () => void
  handleRegenerate: () => void
  handleSaved: (skillId: string) => void
}

interface PendingRunAcceptance {
  requestId: string
  runId: string
  timeoutId: number
  resolve: () => void
  reject: (error: Error) => void
}

export function useSkillCreatorRun(): UseSkillCreatorRunReturn {
  const searchParams = useSearchParams()
  const router = useRouter()
  const routeEditSkillId = searchParams.get('edit') || null
  const runParam = searchParams.get('run') || null

  const [messages, setMessages] = useState<Message[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<SkillPreviewData | null>(null)
  const [fileTree, setFileTree] = useState<Record<string, { action: string; size?: number; timestamp?: number }>>({})
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [graphReady, setGraphReady] = useState(false)
  const [graphError, setGraphError] = useState<string | null>(null)
  const [projection, setProjection] = useState<SkillCreatorRunProjection>(EMPTY_PROJECTION)
  const [runId, setRunId] = useState<string | null>(runParam)
  const [historyMessages, setHistoryMessages] = useState<Message[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  const graphIdRef = useRef<string | null>(null)
  const threadIdRef = useRef<string | null>(null)
  const currentRequestIdRef = useRef<string | null>(null)
  const clientRef = useRef(getChatWsClient())
  const runWsClientRef = useRef(getRunWsClient())
  const lastSeqRef = useRef(0)
  const activeRunIdRef = useRef<string | null>(runParam)
  const isMountedRef = useRef(true)
  const sendLockRef = useRef(false)
  const pendingAcceptanceRef = useRef<PendingRunAcceptance | null>(null)

  const resolvePendingAcceptance = useCallback((runId?: string | null) => {
    const pending = pendingAcceptanceRef.current
    if (!pending) return false
    if (runId && pending.runId !== runId) return false
    clearTimeout(pending.timeoutId)
    pendingAcceptanceRef.current = null
    pending.resolve()
    return true
  }, [])

  const rejectPendingAcceptance = useCallback((error: Error, runId?: string | null) => {
    const pending = pendingAcceptanceRef.current
    if (!pending) return false
    if (runId && pending.runId !== runId) return false
    clearTimeout(pending.timeoutId)
    pendingAcceptanceRef.current = null
    pending.reject(error)
    return true
  }, [])

  // ---- lifecycle ----
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      currentRequestIdRef.current = null
      activeRunIdRef.current = null
      rejectPendingAcceptance(new Error('Skill creator page unmounted'))
    }
  }, [rejectPendingAcceptance])

  useEffect(() => {
    setRunId(runParam)
  }, [runParam])

  // ---- graph resolution ----
  useEffect(() => {
    async function resolveGraphId() {
      try {
        const response = await apiGet<{ workspaces: Array<{ id: string; type?: string }> }>(
          API_ENDPOINTS.workspaces,
        )
        const personal = (response.workspaces || []).find((workspace) => workspace.type === 'personal')
        if (!personal) {
          if (isMountedRef.current) setGraphError('Personal workspace not found')
          return
        }

        const graph = await findOrCreateGraphByTemplate('Skill Creator', 'skill-creator', personal.id)
        graphIdRef.current = graph.id
        if (isMountedRef.current) setGraphReady(true)
      } catch (error) {
        console.error('Failed to resolve skill-creator graph:', error)
        if (isMountedRef.current) {
          setGraphError(error instanceof Error ? error.message : 'Failed to initialize Skill Creator')
        }
      }
    }

    void resolveGraphId()
  }, [])

  // ---- derive UI state from projection ----
  useEffect(() => {
    const normalized = normalizeProjection(projection)
    const nextMessages = mergeHistoryWithRunMessages(historyMessages, mapProjectionMessages(normalized))
    const nextPreviewData = normalizePreviewData(normalized.preview_data)
    const nextThreadId = normalized.thread_id || null
    const nextStatus = normalized.status || 'idle'

    threadIdRef.current = nextThreadId
    setMessages(nextMessages)
    setPreviewData(nextPreviewData)
    setFileTree(normalized.file_tree || {})
    setThreadId(nextThreadId)
    setIsProcessing(nextStatus === 'queued' || nextStatus === 'running')
  }, [historyMessages, projection])

  const effectiveEditSkillId = routeEditSkillId || projection.edit_skill_id || null

  // ---- auto-discover active run ----
  useEffect(() => {
    if (!graphReady || !graphIdRef.current || runParam) return

    let cancelled = false
    void runService
      .findActiveSkillCreatorRun({ graphId: graphIdRef.current })
      .then((activeRun) => {
        if (cancelled || !activeRun?.run_id) return
        setRunId(activeRun.run_id)
        router.replace(buildSkillCreatorUrl(activeRun.run_id, effectiveEditSkillId))
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Failed to discover active skill creator run:', error)
        }
      })

    return () => {
      cancelled = true
    }
  }, [effectiveEditSkillId, graphReady, router, runParam])

  // ---- load conversation history ----
  useEffect(() => {
    if (!threadId) {
      setHistoryMessages([])
      return
    }

    let cancelled = false
    void conversationService
      .getConversationHistory(threadId, { pageSize: 200 })
      .then((items) => {
        if (cancelled) return
        setHistoryMessages(items.map(mapConversationMessageToUi))
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Failed to load skill creator conversation history:', error)
        }
      })

    return () => {
      cancelled = true
    }
  }, [threadId])

  // ---- run WS handlers ----
  const handleRunSnapshot = useCallback((frame: RunSnapshotFrame) => {
    if (activeRunIdRef.current !== frame.run_id) return
    lastSeqRef.current = frame.last_seq
    setIsSubmitting(false)
    resolvePendingAcceptance(frame.run_id)
    setProjection(normalizeProjection(frame.data))
  }, [resolvePendingAcceptance])

  const handleRunEvent = useCallback((frame: RunEventFrame) => {
    if (activeRunIdRef.current !== frame.run_id) return
    lastSeqRef.current = frame.seq
    setProjection((current) => applySkillCreatorEvent(current, frame.event_type, frame.data || {}))
  }, [])

  const handleRunStatus = useCallback((frame: RunStatusFrame) => {
    if (activeRunIdRef.current !== frame.run_id) return
    setIsSubmitting(false)
    resolvePendingAcceptance(frame.run_id)
    setProjection((current) => {
      const next = cloneProjection(current)
      next.status = frame.status
      if (frame.error_message) {
        next.meta = { ...next.meta, error: frame.error_message }
      }
      return next
    })
  }, [resolvePendingAcceptance])

  // ---- run subscription ----
  useEffect(() => {
    if (!runId) {
      activeRunIdRef.current = null
      lastSeqRef.current = 0
      setIsSubmitting(false)
      rejectPendingAcceptance(new Error('Skill creator run reset before acceptance'))
      setProjection(EMPTY_PROJECTION)
      return
    }

    activeRunIdRef.current = runId
    lastSeqRef.current = 0

    void runWsClientRef.current.subscribe(runId, 0, {
      onSnapshot: handleRunSnapshot,
      onEvent: handleRunEvent,
      onStatus: handleRunStatus,
      onError: (message) => {
        if (activeRunIdRef.current !== runId) return
        setIsSubmitting(false)
        rejectPendingAcceptance(new Error(message), runId)
        console.error('Skill creator run ws error:', message)
      },
    })

    return () => {
      runWsClientRef.current.unsubscribe(runId)
      if (activeRunIdRef.current === runId) {
        activeRunIdRef.current = null
      }
    }
  }, [handleRunEvent, handleRunSnapshot, handleRunStatus, runId])

  // ---- actions ----
  const sendMessage = useCallback(
    async (userPrompt: string) => {
      if (!userPrompt.trim() || sendLockRef.current || !graphReady || !graphIdRef.current) return false
      sendLockRef.current = true
      setIsSubmitting(true)
      let pendingRunId: string | null = null

      try {
        await clientRef.current.connect()

        const createdRun = await runService.createSkillCreatorRun({
          message: userPrompt,
          graph_id: graphIdRef.current,
          thread_id: threadIdRef.current,
          edit_skill_id: effectiveEditSkillId,
        })

        const nextRunId = createdRun.run_id
        pendingRunId = nextRunId
        const requestId = crypto.randomUUID()

        currentRequestIdRef.current = requestId
        activeRunIdRef.current = nextRunId
        lastSeqRef.current = 0
        setRunId(nextRunId)
        router.replace(buildSkillCreatorUrl(nextRunId, effectiveEditSkillId))

        const acceptedPromise = new Promise<void>((resolve, reject) => {
          const timeoutId = window.setTimeout(() => {
            if (!rejectPendingAcceptance(new Error('Timed out waiting for Skill Creator acceptance'), nextRunId)) {
              reject(new Error('Timed out waiting for Skill Creator acceptance'))
            }
          }, 10000)
          pendingAcceptanceRef.current = {
            requestId,
            runId: nextRunId,
            timeoutId,
            resolve,
            reject,
          }
        })

        const handleAccepted = (event: IncomingChatAcceptedEvent) => {
          if (event.request_id !== requestId) return
          resolvePendingAcceptance(nextRunId)
        }

        void clientRef.current
          .sendChat({
            requestId,
            message: userPrompt,
            threadId: createdRun.thread_id,
            graphId: graphIdRef.current,
            metadata: {
              mode: 'skill_creator',
              run_id: nextRunId,
              ...(effectiveEditSkillId ? { edit_skill_id: effectiveEditSkillId } : {}),
            },
            onAccepted: handleAccepted,
          })
          .catch(async (error) => {
            rejectPendingAcceptance(
              error instanceof Error ? error : new Error('Failed to dispatch skill creator chat command'),
              nextRunId,
            )
            console.error('Failed to dispatch skill creator chat command:', error)
            setIsSubmitting(false)
            try {
              await runService.cancelRun(nextRunId)
            } catch (cancelError) {
              console.error('Failed to cancel queued skill creator run:', cancelError)
            }
          })
          .finally(() => {
            if (currentRequestIdRef.current === requestId) {
              currentRequestIdRef.current = null
            }
            sendLockRef.current = false
          })

        await acceptedPromise
        return true
      } catch (error) {
        console.error('Failed to start skill creator run:', error)
        setIsSubmitting(false)
        rejectPendingAcceptance(
          error instanceof Error ? error : new Error('Failed to start skill creator run'),
        )
        if (pendingRunId) {
          try {
            await runService.cancelRun(pendingRunId)
          } catch (cancelError) {
            console.error('Failed to cancel skill creator run after start failure:', cancelError)
          }
        }
        sendLockRef.current = false
        return false
      }
    },
    [effectiveEditSkillId, graphReady, rejectPendingAcceptance, resolvePendingAcceptance, router],
  )

  const stopMessage = useCallback(() => {
    const requestId = currentRequestIdRef.current
    if (requestId) {
      clientRef.current.stopByRequestId(requestId)
    }
    if (runId) {
      void runService.cancelRun(runId).catch((error) => {
        console.error('Failed to cancel skill creator run:', error)
      })
    }
    currentRequestIdRef.current = null
  }, [runId])

  const handleRegenerate = useCallback(() => {
    void sendMessage('Please regenerate the skill with improvements based on the validation feedback.')
  }, [sendMessage])

  const handleSaved = useCallback(
    (_skillId: string) => {
      router.push('/skills')
    },
    [router],
  )

  const hasRunState = !!runId || messages.length > 0 || !!threadId

  return {
    messages,
    isProcessing,
    isSubmitting,
    threadId,
    previewData,
    fileTree,
    graphReady,
    graphError,
    effectiveEditSkillId,
    hasRunState,
    showSaveDialog,
    setShowSaveDialog,
    sendMessage,
    stopMessage,
    handleRegenerate,
    handleSaved,
  }
}

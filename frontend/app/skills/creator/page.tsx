'use client'

import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams, useRouter } from 'next/navigation'
import React, { useState, useCallback, useRef, useEffect } from 'react'

import { findOrCreateGraphByTemplate } from '@/app/chat/services/utils/graphLookup'
import { formatToolDisplay } from '@/app/chat/shared/ToolCallDisplay'
import { generateId, type Message, type ToolCall } from '@/app/chat/types'
import { Button } from '@/components/ui/button'
import { apiGet, API_ENDPOINTS } from '@/lib/api-client'
import { getWsChatUrl } from '@/lib/utils/wsUrl'
import type { ChatStreamEvent, ToolEndEventData } from '@/services/chatBackend'

import SkillCreatorChat from './components/SkillCreatorChat'
import SkillPreviewPanel from './components/SkillPreviewPanel'
import SkillSaveDialog from './components/SkillSaveDialog'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SkillPreviewData {
  skill_name: string
  files: Array<{
    path: string
    content: string
    file_type: string
    size: number
  }>
  validation: {
    valid: boolean
    errors: string[]
    warnings: string[]
  }
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function SkillCreatorPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const editSkillId = searchParams.get('edit') || null

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const threadIdRef = useRef<string | null>(null)
  const currentRequestIdRef = useRef<string | null>(null)
  const currentAssistantMsgIdRef = useRef<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const connectPromiseRef = useRef<Promise<void> | null>(null)
  const connectResolveRef = useRef<(() => void) | null>(null)
  const connectRejectRef = useRef<((error: Error) => void) | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptsRef = useRef(0)

  // Preview state
  const [previewData, setPreviewData] = useState<SkillPreviewData | null>(null)
  const [fileTree, setFileTree] = useState<Record<string, { action: string; size?: number; timestamp?: number }>>({})

  // Save dialog
  const [showSaveDialog, setShowSaveDialog] = useState(false)

  // Resolved graph ID for skill creator
  const graphIdRef = useRef<string | null>(null)
  const [graphReady, setGraphReady] = useState(false)
  const [graphError, setGraphError] = useState<string | null>(null)

  // Track mounted state
  const isMountedRef = useRef(true)
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      currentRequestIdRef.current = null
      currentAssistantMsgIdRef.current = null
      if (wsRef.current) {
        wsRef.current.onopen = null
        wsRef.current.onmessage = null
        wsRef.current.onclose = null
        wsRef.current.onerror = null
        if (
          wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING
        ) {
          wsRef.current.close()
        }
        wsRef.current = null
      }
    }
  }, [])

  const ensureWsConnected = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    if (connectPromiseRef.current) return connectPromiseRef.current

    connectPromiseRef.current = new Promise<void>((resolve, reject) => {
      connectResolveRef.current = resolve
      connectRejectRef.current = reject
    })

    getWsChatUrl().then((wsUrl) => {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

    ws.onmessage = (event) => {
      let evt: (Partial<ChatStreamEvent> & { type?: string; request_id?: string; message?: string; data?: any }) | null =
        null
      try {
        evt = JSON.parse(event.data)
      } catch {
        return
      }
      if (!evt) return

      const currentRequestId = currentRequestIdRef.current
      const type = evt.type as string | undefined
      if (type === 'pong') return
      if (type === 'ws_error') {
        console.error('Skill creator ws error:', evt.message)
        const aiMsgId = currentAssistantMsgIdRef.current
        if (aiMsgId) {
          safeSetMessages((prev) =>
            prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
          )
        }
        currentRequestIdRef.current = null
        currentAssistantMsgIdRef.current = null
        if (isMountedRef.current) setIsProcessing(false)
        return
      }
      if (!currentRequestId || evt.request_id !== currentRequestId) return

      const { thread_id, timestamp, data } = evt
      if (thread_id) {
        threadIdRef.current = thread_id
      }

      const aiMsgId = currentAssistantMsgIdRef.current
      if (!aiMsgId) return

      if (type === 'thread_id') return

      if (type === 'file_event') {
        const { action, path, size, timestamp } = data as {
          action: string
          path: string
          size?: number
          timestamp?: number
        }
        setFileTree((prev) => {
          const next = { ...prev }
          if (action === 'delete') {
            delete next[path]
          } else {
            next[path] = { action, size, timestamp }
          }
          return next
        })
        return
      }

      if (type === 'content') {
        const delta = (data as { delta?: string })?.delta || ''
        if (!delta) return
        safeSetMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + delta } : m)),
        )
        return
      }

      if (type === 'tool_start') {
        const toolData = data as { tool_name?: string; tool_input?: any }
        const toolName = toolData?.tool_name || 'tool'
        const toolInput = toolData?.tool_input || {}
        const toolId = generateId()
        const { label, detail } = formatToolDisplay(toolName, toolInput)
        const tool: ToolCall = {
          id: toolId,
          name: label,
          args: { ...toolInput, _detail: detail, _rawName: toolName },
          status: 'running',
          startTime: timestamp || Date.now(),
        }
        safeSetMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsgId ? { ...m, tool_calls: [...(m.tool_calls || []), tool] } : m,
          ),
        )
        return
      }

      if (type === 'tool_end') {
        const toolData = data as ToolEndEventData
        const toolName = toolData?.tool_name || 'tool'
        const toolOutput = toolData?.tool_output

        if (toolName === 'preview_skill' && toolOutput) {
          try {
            const parsed: SkillPreviewData =
              typeof toolOutput === 'string' ? JSON.parse(toolOutput) : toolOutput
            if (parsed && parsed.files) {
              setPreviewData(parsed)
            }
          } catch {
            if (toolOutput?.skill_name && toolOutput?.files) {
              setPreviewData(toolOutput as SkillPreviewData)
            }
          }
        }

        safeSetMessages((prev) =>
          prev.map((m) => {
            if (m.id !== aiMsgId) return m
            const targetTool = [...(m.tool_calls || [])].reverse().find((t) => t.status === 'running')
            if (!targetTool) return m
            return {
              ...m,
              tool_calls: (m.tool_calls || []).map((t) =>
                t.id === targetTool.id
                  ? {
                      ...t,
                      status: 'completed' as const,
                      endTime: timestamp || Date.now(),
                      result: toolOutput,
                    }
                  : t,
              ),
            }
          }),
        )
        return
      }

      if (type === 'error') {
        const errMsg = (data as { message?: string })?.message || 'Unknown error'
        if (errMsg === 'Stream stopped' || errMsg.includes('stopped')) {
          safeSetMessages((prev) =>
            prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
          )
        } else {
          safeSetMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsgId
                ? { ...m, content: (m.content || '') + `\n\n*Error: ${errMsg}*` }
                : m,
            ),
          )
        }
        currentRequestIdRef.current = null
        currentAssistantMsgIdRef.current = null
        setIsProcessing(false)
        return
      }

      if (type === 'done' || type === 'interrupt') {
        safeSetMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
        )
        currentRequestIdRef.current = null
        currentAssistantMsgIdRef.current = null
        setIsProcessing(false)
      }
    }

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0
      connectResolveRef.current?.()
      connectPromiseRef.current = null
      connectResolveRef.current = null
      connectRejectRef.current = null
    }

    ws.onerror = () => {
      connectRejectRef.current?.(new Error('WebSocket connection failed'))
      connectPromiseRef.current = null
      connectResolveRef.current = null
      connectRejectRef.current = null
    }

    ws.onclose = () => {
      const aiMsgId = currentAssistantMsgIdRef.current
      if (aiMsgId) {
        safeSetMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
        )
      }
      currentAssistantMsgIdRef.current = null
      if (isMountedRef.current && currentRequestIdRef.current) {
        setIsProcessing(false)
      }
      currentRequestIdRef.current = null
      connectPromiseRef.current = null
      connectResolveRef.current = null
      connectRejectRef.current = null
      wsRef.current = null

      // Reconnect with exponential backoff while page is mounted and idle
      if (isMountedRef.current && !currentRequestIdRef.current) {
        const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 15000)
        reconnectAttemptsRef.current += 1
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null
          if (isMountedRef.current) {
            ensureWsConnected().catch(() => {/* will retry on next close */})
          }
        }, delay)
      }
    }
    }).catch((err) => {
      connectRejectRef.current?.(err instanceof Error ? err : new Error(String(err)))
      connectPromiseRef.current = null
      connectResolveRef.current = null
      connectRejectRef.current = null
    })

    return connectPromiseRef.current
  }, [])

  // Resolve skill-creator graph ID on mount (uses shared lock to prevent duplicate creation)
  useEffect(() => {
    async function resolveGraphId() {
      try {
        // Find personal workspace
        const response = await apiGet<{ workspaces: Array<{ id: string; type?: string }> }>(
          API_ENDPOINTS.workspaces,
        )
        const personal = (response.workspaces || []).find((w) => w.type === 'personal')
        if (!personal) {
          if (isMountedRef.current) setGraphError('Personal workspace not found')
          return
        }

        // Find or create via shared utility (same lock as skillCreatorHandler)
        const graph = await findOrCreateGraphByTemplate(
          'Skill Creator',
          'skill-creator',
          personal.id,
        )
        graphIdRef.current = graph.id
        if (isMountedRef.current) setGraphReady(true)
      } catch (error) {
        console.error('Failed to resolve skill-creator graph:', error)
        if (isMountedRef.current) {
          setGraphError(
            error instanceof Error ? error.message : 'Failed to initialize Skill Creator',
          )
        }
      }
    }

    resolveGraphId()
  }, [])

  // ---- Safe state updater ----
  const safeSetMessages = useCallback((updater: React.SetStateAction<Message[]>) => {
    if (isMountedRef.current) setMessages(updater)
  }, [])

  // ---- Send message (inlined streaming logic so we can intercept preview_skill) ----
  const sendMessage = useCallback(
    async (userPrompt: string) => {
      if (!userPrompt.trim() || isProcessing || !graphReady) return

      // Add user message
      const userMsg: Message = {
        id: generateId(),
        role: 'user',
        content: userPrompt,
        timestamp: Date.now(),
      }
      safeSetMessages((prev) => [...prev, userMsg])

      setIsProcessing(true)
      setFileTree({})

      // Prepare assistant placeholder
      const aiMsgId = generateId()
      const initialAiMsg: Message = {
        id: aiMsgId,
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        isStreaming: true,
        tool_calls: [],
      }
      safeSetMessages((prev) => [...prev, initialAiMsg])
      currentAssistantMsgIdRef.current = aiMsgId
      try {
        await ensureWsConnected()
        const requestId = crypto.randomUUID()
        currentRequestIdRef.current = requestId
        wsRef.current?.send(
          JSON.stringify({
            type: 'chat',
            request_id: requestId,
            thread_id: threadIdRef.current,
            graph_id: graphIdRef.current,
            message: userPrompt,
            metadata: {
              ...(editSkillId ? { edit_skill_id: editSkillId } : {}),
            },
          }),
        )
      } catch (e: any) {
        safeSetMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsgId
              ? { ...m, isStreaming: false, content: (m.content || '') + `\n\n*Error: ${String(e?.message || e)}*` }
              : m,
          ),
        )
        currentRequestIdRef.current = null
        currentAssistantMsgIdRef.current = null
        if (isMountedRef.current) setIsProcessing(false)
      }
    },
    [isProcessing, editSkillId, safeSetMessages, graphReady, ensureWsConnected],
  )

  // ---- Stop streaming ----
  const stopMessage = useCallback(() => {
    if (currentRequestIdRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop', request_id: currentRequestIdRef.current }))
    }
    currentRequestIdRef.current = null
    currentAssistantMsgIdRef.current = null
    setIsProcessing(false)
  }, [])

  // ---- Regenerate: ask AI to regenerate the skill ----
  const handleRegenerate = useCallback(() => {
    sendMessage('Please regenerate the skill with improvements based on the validation feedback.')
  }, [sendMessage])

  // ---- Save callback ----
  const handleSaved = useCallback(
    (_skillId: string) => {
      // Navigate to skills page after save
      router.push('/skills')
    },
    [router],
  )

  return (
    <div className="flex h-screen flex-col bg-white">
      {/* Top bar */}
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-gray-100 px-4 py-2.5">
        <Link href="/skills">
          <Button variant="ghost" size="sm" className="gap-1.5 text-gray-600 hover:text-gray-800">
            <ArrowLeft size={14} />
            <span className="text-xs">Skills</span>
          </Button>
        </Link>
        <div className="h-4 w-px bg-gray-200" />
        <h1 className="text-sm font-semibold text-gray-800">
          {editSkillId ? 'Edit Skill' : 'Create Skill'}
        </h1>
      </div>

      {/* Main split layout */}
      <div className="flex min-h-0 flex-1">
        {/* Left: Chat panel */}
        <div className="flex min-w-0 flex-1 flex-col border-r border-gray-100">
          {graphError ? (
            <div className="flex flex-1 items-center justify-center text-sm text-red-500">
              {graphError}
            </div>
          ) : !graphReady ? (
            <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
              Initializing Skill Creator...
            </div>
          ) : (
            <SkillCreatorChat
              messages={messages}
              isProcessing={isProcessing}
              onSendMessage={sendMessage}
              onStop={stopMessage}
            />
          )}
        </div>

        {/* Right: Preview panel */}
        <div className="flex w-[480px] flex-shrink-0 flex-col">
          <SkillPreviewPanel
            previewData={previewData}
            fileTree={fileTree}
            threadId={threadIdRef.current}
            isProcessing={isProcessing}
            onSave={() => setShowSaveDialog(true)}
            onRegenerate={handleRegenerate}
          />
        </div>
      </div>

      {/* Save dialog */}
      <SkillSaveDialog
        open={showSaveDialog}
        onOpenChange={setShowSaveDialog}
        previewData={previewData}
        fileTree={fileTree}
        threadId={threadIdRef.current}
        editSkillId={editSkillId}
        onSaved={handleSaved}
      />
    </div>
  )
}

'use client'

import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams, useRouter } from 'next/navigation'
import React, { useState, useCallback, useRef, useEffect } from 'react'

import { Button } from '@/components/ui/button'

import { streamChat, type ChatStreamEvent, type ToolEndEventData } from '@/services/chatBackend'

import { generateId, type Message, type ToolCall } from '@/app/chat/types'
import { findOrCreateGraphByTemplate } from '@/app/chat/services/utils/graphLookup'
import { apiGet, API_ENDPOINTS } from '@/lib/api-client'

import { formatToolDisplay } from './components/toolDisplayUtils'
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
  const abortRef = useRef<AbortController | null>(null)
  const threadIdRef = useRef<string | null>(null)

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
      abortRef.current?.abort()
    }
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
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

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

      const lastRunningToolIdByName: Record<string, string> = {}

      try {
        const result = await streamChat({
          message: userPrompt,
          threadId: threadIdRef.current,
          graphId: graphIdRef.current,
          metadata: {
            ...(editSkillId ? { edit_skill_id: editSkillId } : {}),
          },
          signal: ac.signal,
          onEvent: (evt: ChatStreamEvent) => {
            const { type, thread_id, timestamp, data } = evt

            // Track thread id
            if (thread_id) {
              threadIdRef.current = thread_id
            }

            if (type === 'thread_id') return

            // ---- File events (incremental file tracking) ----
            if (type === 'file_event') {
              const { action, path, size, timestamp } = data as {
                action: string; path: string; size?: number; timestamp?: number
              }
              setFileTree(prev => {
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

            // ---- Content (streaming text) ----
            if (type === 'content') {
              const delta = (data as { delta?: string })?.delta || ''
              if (!delta) return
              safeSetMessages((prev) =>
                prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + delta } : m)),
              )
              return
            }

            // ---- Tool start ----
            if (type === 'tool_start') {
              const toolData = data as { tool_name?: string; tool_input?: any }
              const toolName = toolData?.tool_name || 'tool'
              const toolInput = toolData?.tool_input || {}
              const toolId = generateId()
              lastRunningToolIdByName[toolName] = toolId

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

            // ---- Tool end (intercept preview_skill) ----
            if (type === 'tool_end') {
              const toolData = data as ToolEndEventData
              const toolName = toolData?.tool_name || 'tool'
              const toolOutput = toolData?.tool_output
              const toolId = lastRunningToolIdByName[toolName]

              // Intercept preview_skill to extract preview data
              if (toolName === 'preview_skill' && toolOutput) {
                try {
                  const parsed: SkillPreviewData =
                    typeof toolOutput === 'string' ? JSON.parse(toolOutput) : toolOutput
                  if (parsed && parsed.files) {
                    setPreviewData(parsed)
                  }
                } catch {
                  // If parsing fails, try to find preview data in nested structure
                  if (toolOutput?.skill_name && toolOutput?.files) {
                    setPreviewData(toolOutput as SkillPreviewData)
                  }
                }
              }

              if (!toolId) return

              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== aiMsgId) return m
                  const tools = (m.tool_calls || []).map((t) =>
                    t.id === toolId
                      ? {
                          ...t,
                          status: 'completed' as const,
                          endTime: timestamp || Date.now(),
                          result: toolOutput,
                        }
                      : t,
                  )
                  return { ...m, tool_calls: tools }
                }),
              )
              return
            }

            // ---- Error ----
            if (type === 'error') {
              const errMsg = (data as { message?: string })?.message || 'Unknown error'
              if (errMsg === 'Stream stopped' || errMsg.includes('stopped')) {
                safeSetMessages((prev) =>
                  prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
                )
                return
              }
              safeSetMessages((prev) =>
                prev.map((m) =>
                  m.id === aiMsgId
                    ? { ...m, content: (m.content || '') + `\n\n*Error: ${errMsg}*` }
                    : m,
                ),
              )
              return
            }

            // ---- Done ----
            if (type === 'done') {
              safeSetMessages((prev) =>
                prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
              )
              return
            }
          },
        })

        if (result.threadId) {
          threadIdRef.current = result.threadId
        }
      } catch (e: any) {
        if (e?.name !== 'AbortError') {
          safeSetMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsgId
                ? { ...m, content: (m.content || '') + `\n\n*Error: ${String(e?.message || e)}*` }
                : m,
            ),
          )
        }
      } finally {
        safeSetMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m)),
        )
        if (isMountedRef.current) {
          setIsProcessing(false)
        }
      }
    },
    [isProcessing, editSkillId, safeSetMessages, graphReady],
  )

  // ---- Stop streaming ----
  const stopMessage = useCallback(() => {
    abortRef.current?.abort()
    setIsProcessing(false)
  }, [])

  // ---- Regenerate: ask AI to regenerate the skill ----
  const handleRegenerate = useCallback(() => {
    sendMessage('Please regenerate the skill with improvements based on the validation feedback.')
  }, [sendMessage])

  // ---- Save callback ----
  const handleSaved = useCallback(
    (skillId: string) => {
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
        editSkillId={editSkillId}
        onSaved={handleSaved}
      />
    </div>
  )
}

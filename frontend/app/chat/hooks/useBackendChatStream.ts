'use client'

import { useCallback, useRef, useState, useEffect } from 'react'

import {
  streamChat,
  type ChatStreamEvent,
  type ContentEventData,
  type ToolStartEventData,
  type ToolEndEventData,
  type ErrorEventData,
  type NodeStartEventData,
  type NodeEndEventData,
  type CommandEventData,
  type RouteDecisionEventData,
} from '@/services/chatBackend'

import { toastError } from '@/lib/utils/toast'
import { generateId, type Message, type ToolCall } from '../types'
import type { ChatAction } from './useChatReducer'

function now() {
  return Date.now()
}

/**
 * Backend chat stream hook.
 *
 * Accepts a dispatch function from useChatReducer.
 * All SSE events are translated into ChatAction dispatches.
 */
export const useBackendChatStream = (
  dispatch: React.Dispatch<ChatAction>,
) => {

  const [isProcessing, setIsProcessing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const currentThreadIdRef = useRef<string | null>(null)
  const currentMsgIdRef = useRef<string>('')
  const isMountedRef = useRef(true)

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  const stopMessage = useCallback(async (threadId: string | null) => {
    const targetThreadId = threadId || currentThreadIdRef.current

    abortRef.current?.abort()

    if (!targetThreadId) {
      setIsProcessing(false)
      return
    }

    try {
      const { apiPost } = await import('@/lib/api-client')
      await apiPost('chat/stop', { thread_id: targetThreadId })
      setIsProcessing(false)
    } catch (error) {
      console.error('Failed to stop chat:', error)
      setIsProcessing(false)
    }
  }, [])

  const sendMessage = useCallback(
    async (
      userPrompt: string,
      opts: { threadId?: string | null; graphId?: string | null; metadata?: Record<string, any> },
    ) => {
      if (!userPrompt.trim()) return { threadId: opts.threadId || undefined }

      setIsProcessing(true)
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      const aiMsgId = generateId()
      currentMsgIdRef.current = aiMsgId

      const initialAiMsg: Message = {
        id: aiMsgId,
        role: 'assistant',
        content: '',
        timestamp: now(),
        isStreaming: true,
        tool_calls: [],
      }

      dispatch({ type: 'APPEND_MESSAGE', message: initialAiMsg })

      // Map tool_name -> last running tool id (since backend doesn't emit ids)
      const lastRunningToolIdByName: Record<string, string> = {}
      let latestThreadId: string | undefined = opts.threadId || undefined
      currentThreadIdRef.current = latestThreadId || null

      try {
        const result = await streamChat({
          message: userPrompt,
          threadId: opts.threadId || null,
          graphId: opts.graphId || null,
          metadata: opts.metadata,
          signal: ac.signal,
          onEvent: (evt: ChatStreamEvent) => {
            const { type, thread_id, run_id, node_name, timestamp, data } = evt

            // Update thread_id
            if (thread_id) {
              latestThreadId = thread_id
              currentThreadIdRef.current = thread_id
              dispatch({ type: 'SET_THREAD', threadId: thread_id })
            }

            if (type === 'thread_id') return

            // ─── Content ───────────────────────────────────────────────
            if (type === 'content') {
              const contentData = data as ContentEventData
              const delta = contentData?.delta || ''
              if (!delta) return

              dispatch({
                type: 'STREAM_CONTENT',
                delta,
                messageId: aiMsgId,
                metadata: { lastNode: node_name, lastRunId: run_id, lastUpdate: timestamp },
              })
              return
            }

            // ─── Tool Start ────────────────────────────────────────────
            if (type === 'tool_start') {
              const toolData = data as ToolStartEventData
              const toolName = toolData?.tool_name || 'tool'
              const toolInput = toolData?.tool_input || {}
              const toolId = generateId()
              lastRunningToolIdByName[toolName] = toolId

              dispatch({
                type: 'TOOL_START',
                tool: {
                  id: toolId,
                  name: toolName,
                  args: toolInput,
                  status: 'running',
                  startTime: timestamp || now(),
                },
              })
              return
            }

            // ─── File Event ────────────────────────────────────────────
            if (type === 'file_event') {
              const { action, path, size, timestamp: ts } = data as {
                action: string; path: string; size?: number; timestamp?: number
              }

              // Update preview panel fileTree state
              dispatch({
                type: 'FILE_EVENT',
                path,
                info: { action, size, timestamp: ts },
              })
              return
            }

            // ─── Tool End ──────────────────────────────────────────────
            if (type === 'tool_end') {
              const toolData = data as ToolEndEventData
              const toolName = toolData?.tool_name || 'tool'
              const toolOutput = toolData?.tool_output
              const toolId = lastRunningToolIdByName[toolName]
              if (!toolId) return

              dispatch({ type: 'TOOL_END', id: toolId, result: toolOutput })
              return
            }

            // ─── Error ─────────────────────────────────────────────────
            if (type === 'error') {
              const errorData = data as ErrorEventData
              const errorMsg = errorData?.message || 'Unknown error'

              if (errorMsg === 'Stream stopped' || errorMsg.includes('stopped')) {
                dispatch({ type: 'UPDATE_MESSAGE', id: aiMsgId, patch: { isStreaming: false } })
                return
              }

              // Append error to message content (we don't have current content,
              // so we dispatch a special update)
              dispatch({ type: 'STREAM_ERROR', error: errorMsg })
              toastError(errorMsg)
              return
            }

            // ─── Done ──────────────────────────────────────────────────
            if (type === 'done') {
              dispatch({ type: 'UPDATE_MESSAGE', id: aiMsgId, patch: { isStreaming: false } })
              return
            }

            // ─── Status ────────────────────────────────────────────────
            if (type === 'status') return

            // ─── Node Start ────────────────────────────────────────────
            if (type === 'node_start') {
              const nodeData = data as NodeStartEventData
              const nodeLabel = nodeData?.node_label || node_name || 'Unknown Node'
              const nodeId = nodeData?.node_id || node_name || ''

              dispatch({ type: 'NODE_START', nodeId, label: nodeLabel })
              dispatch({
                type: 'NODE_LOG',
                entry: {
                  type: 'node_start',
                  nodeName: nodeLabel,
                  timestamp,
                  data: { nodeId },
                },
              })
              return
            }

            // ─── Node End ──────────────────────────────────────────────
            if (type === 'node_end') {
              const nodeData = data as NodeEndEventData
              const nodeLabel = nodeData?.node_label || node_name || 'Unknown Node'
              const nodeId = nodeData?.node_id || node_name || ''

              dispatch({ type: 'NODE_END', nodeId })
              dispatch({
                type: 'NODE_LOG',
                entry: {
                  type: 'node_end',
                  nodeName: nodeLabel,
                  timestamp,
                  data: {
                    nodeId,
                    status: nodeData?.status || 'completed',
                    duration: nodeData?.duration,
                  },
                },
              })

              // Update lastNode on message
              dispatch({
                type: 'UPDATE_MESSAGE',
                id: aiMsgId,
                patch: { metadata: { lastNode: nodeLabel } },
              })
              return
            }

            // ─── Command ───────────────────────────────────────────────
            if (type === 'command') {
              const commandData = data as CommandEventData
              const stateUpdate = commandData?.update || {}

              dispatch({
                type: 'NODE_LOG',
                entry: {
                  type: 'command',
                  nodeName: node_name || 'unknown',
                  timestamp,
                  data: {
                    update: stateUpdate,
                    goto: commandData?.goto,
                    reason: commandData?.reason,
                    hasStateChanges: Object.keys(stateUpdate).length > 0,
                  },
                },
              })
              return
            }

            // ─── Route Decision ────────────────────────────────────────
            if (type === 'route_decision') {
              const decisionData = data as RouteDecisionEventData

              dispatch({
                type: 'NODE_LOG',
                entry: {
                  type: 'route_decision',
                  nodeName: decisionData?.node_id || 'unknown',
                  timestamp,
                  data: {
                    nodeType: decisionData?.node_type,
                    result: decisionData?.result,
                    reason: decisionData?.reason,
                    goto: decisionData?.goto,
                  },
                },
              })
              return
            }

            // ─── Loop Iteration ────────────────────────────────────────
            if (type === 'loop_iteration') {
              const iterationData = data as any

              dispatch({
                type: 'NODE_LOG',
                entry: {
                  type: 'loop_iteration',
                  nodeName: iterationData?.loop_node_id || 'unknown',
                  timestamp,
                  data: {
                    iteration: iterationData?.iteration,
                    maxIterations: iterationData?.max_iterations,
                    conditionMet: iterationData?.condition_met,
                    reason: iterationData?.reason,
                  },
                },
              })
              return
            }

            // ─── Parallel Task ─────────────────────────────────────────
            if (type === 'parallel_task') {
              const taskData = data as any

              dispatch({
                type: 'NODE_LOG',
                entry: {
                  type: 'parallel_task',
                  nodeName: 'system',
                  timestamp,
                  data: {
                    taskId: taskData?.task_id,
                    status: taskData?.status,
                    result: taskData?.result,
                    errorMsg: taskData?.error_msg,
                  },
                },
              })
              return
            }

            // ─── State Update ──────────────────────────────────────────
            if (type === 'state_update') {
              // State updates are informational — no action needed beyond logging
              return
            }
          },
        })

        if (result.threadId) {
          latestThreadId = result.threadId
          currentThreadIdRef.current = result.threadId
          dispatch({ type: 'SET_THREAD', threadId: result.threadId })
        }
      } catch (e: any) {
        if (e?.name !== 'AbortError') {
          const msg = `Error: ${String(e?.message || e)}`
          dispatch({
            type: 'UPDATE_MESSAGE',
            id: aiMsgId,
            patch: { content: `\n\n*${msg}*` },
          })
        }
      } finally {
        dispatch({ type: 'UPDATE_MESSAGE', id: aiMsgId, patch: { isStreaming: false } })
        dispatch({ type: 'STREAM_DONE' })
        if (isMountedRef.current) {
          setIsProcessing(false)
        }
      }

      return { threadId: latestThreadId }
    },
    [dispatch],
  )

  return { sendMessage, stopMessage, isProcessing }
}

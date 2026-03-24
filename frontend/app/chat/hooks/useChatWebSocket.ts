'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { getWsChatUrl } from '@/lib/utils/wsUrl'
import { toastError } from '@/lib/utils/toast'
import type {
  ChatStreamEvent,
  CommandEventData,
  ContentEventData,
  ErrorEventData,
  NodeEndEventData,
  NodeStartEventData,
  RouteDecisionEventData,
  ToolEndEventData,
  ToolStartEventData,
} from '@/services/chatBackend'

import { generateId, type Message } from '../types'

import type { ChatAction } from './useChatReducer'

function now() {
  return Date.now()
}

interface ActiveRequest {
  aiMsgId: string
  lastRunningToolIdByName: Record<string, string>
}

interface SendMessageOpts {
  message: string
  threadId?: string | null
  graphId?: string | null
  metadata?: Record<string, any>
}

interface ResumeOpts {
  threadId: string
  command: { update?: Record<string, any>; goto?: string | null }
}

export interface UseChatWebSocketReturn {
  isConnected: boolean
  sendMessage: (opts: SendMessageOpts) => Promise<{ requestId: string }>
  stopMessage: (threadId: string | null) => void
  resumeChat: (opts: ResumeOpts) => Promise<{ requestId: string }>
}

type IncomingChatWsEvent = Partial<ChatStreamEvent> & {
  type?: string
  request_id?: string
  message?: string
  thread_id?: string
  data?: any
  run_id?: string
  node_name?: string
  timestamp?: number
}

export function useChatWebSocket(dispatch: React.Dispatch<ChatAction>): UseChatWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const activeRequestsRef = useRef<Record<string, ActiveRequest>>({})
  const activeByThreadRef = useRef(new Map<string, string>())
  const activeThreadIdRef = useRef<string | null>(null)
  const isUnmountingRef = useRef(false)
  const connectPromiseRef = useRef<Promise<void> | null>(null)
  const connectResolveRef = useRef<(() => void) | null>(null)
  const connectRejectRef = useRef<((error: Error) => void) | null>(null)

  const [isConnected, setIsConnected] = useState(false)

  const cleanupSocket = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }
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
    setIsConnected(false)
  }, [])

  const finalizeActiveRequests = useCallback(
    (errorMessage: string) => {
      const activeRequests = activeRequestsRef.current
      Object.values(activeRequests).forEach(({ aiMsgId }) => {
        dispatch({ type: 'STREAM_ERROR', error: errorMessage })
        dispatch({ type: 'STREAM_DONE', messageId: aiMsgId })
      })
      activeRequestsRef.current = {}
      activeByThreadRef.current.clear()
      activeThreadIdRef.current = null
    },
    [dispatch],
  )

  const scheduleReconnect = useCallback(() => {
    if (isUnmountingRef.current) return
    const delay = Math.min(1000 * (2 ** reconnectAttemptsRef.current), 10000)
    reconnectAttemptsRef.current += 1
    reconnectTimeoutRef.current = setTimeout(() => {
      reconnectTimeoutRef.current = null
      void connect()
    }, delay)
  }, [])

  const handleEvent = useCallback(
    (evt: IncomingChatWsEvent) => {
      const { request_id, thread_id, run_id, node_name, timestamp, data } = evt
      const type = evt.type as string | undefined
      const eventTimestamp = timestamp ?? now()

      if (type === 'pong') return

      if (type === 'ws_error') {
        const message = evt.message || 'WebSocket protocol error'
        if (request_id) {
          const activeRequest = activeRequestsRef.current[request_id]
          if (activeRequest) {
            dispatch({ type: 'STREAM_DONE', messageId: activeRequest.aiMsgId })
            delete activeRequestsRef.current[request_id]
          }
          if (thread_id) activeByThreadRef.current.delete(thread_id)
        }
        dispatch({ type: 'STREAM_ERROR', error: message })
        toastError(message)
        return
      }

      if (thread_id && request_id) {
        activeByThreadRef.current.set(thread_id, request_id)
        if (activeThreadIdRef.current !== thread_id) {
          activeThreadIdRef.current = thread_id
          dispatch({ type: 'SET_THREAD', threadId: thread_id })
        }
      }

      const activeRequest = request_id ? activeRequestsRef.current[request_id] : undefined
      if (type === 'thread_id') return

      if (type === 'content') {
        if (!activeRequest) return
        const contentData = data as ContentEventData
        const delta = contentData?.delta || ''
        if (!delta) return
        dispatch({
          type: 'STREAM_CONTENT',
          delta,
          messageId: activeRequest.aiMsgId,
          metadata: { lastNode: node_name, lastRunId: run_id, lastUpdate: timestamp },
        })
        return
      }

      if (type === 'tool_start') {
        if (!activeRequest) return
        const toolData = data as ToolStartEventData
        const toolName = toolData?.tool_name || 'tool'
        const toolInput = toolData?.tool_input || {}
        const toolId = generateId()
        activeRequest.lastRunningToolIdByName[toolName] = toolId
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

      if (type === 'file_event') {
        const { action, path, size, timestamp: ts } = data as {
          action: string
          path: string
          size?: number
          timestamp?: number
        }
        dispatch({
          type: 'FILE_EVENT',
          path,
          info: { action, size, timestamp: ts },
        })
        return
      }

      if (type === 'tool_end') {
        if (!activeRequest) return
        const toolData = data as ToolEndEventData
        const toolName = toolData?.tool_name || 'tool'
        const toolId = activeRequest.lastRunningToolIdByName[toolName]
        if (!toolId) return
        dispatch({ type: 'TOOL_END', id: toolId, result: toolData?.tool_output })
        return
      }

      if (type === 'error') {
        const errorData = data as ErrorEventData
        const errorMsg = errorData?.message || 'Unknown error'
        if (errorMsg === 'Stream stopped' || errorMsg.includes('stopped')) {
          if (activeRequest) {
            dispatch({ type: 'STREAM_DONE', messageId: activeRequest.aiMsgId })
            delete activeRequestsRef.current[request_id!]
          }
          if (thread_id) {
            activeByThreadRef.current.delete(thread_id)
          }
          return
        }
        dispatch({ type: 'STREAM_ERROR', error: errorMsg })
        toastError(errorMsg)
        if (activeRequest) {
          dispatch({ type: 'STREAM_DONE', messageId: activeRequest.aiMsgId })
          delete activeRequestsRef.current[request_id!]
        }
        if (thread_id) {
          activeByThreadRef.current.delete(thread_id)
        }
        return
      }

      if (type === 'done') {
        if (activeRequest) {
          dispatch({ type: 'STREAM_DONE', messageId: activeRequest.aiMsgId })
          delete activeRequestsRef.current[request_id!]
        }
        if (thread_id) {
          activeByThreadRef.current.delete(thread_id)
        }
        return
      }

      if (type === 'status') return

      if (type === 'interrupt') {
        if (activeRequest) {
          dispatch({ type: 'STREAM_DONE', messageId: activeRequest.aiMsgId })
          delete activeRequestsRef.current[request_id!]
        }
        if (thread_id) {
          activeByThreadRef.current.delete(thread_id)
          dispatch({
            type: 'SET_INTERRUPT',
            interrupt: {
              nodeName:
                typeof data?.node_name === 'string' ? data.node_name : node_name || 'unknown',
              nodeLabel:
                typeof data?.node_label === 'string' ? data.node_label : node_name || 'Unknown Node',
              state:
                data && typeof data === 'object' && data.state && typeof data.state === 'object'
                  ? (data.state as Record<string, unknown>)
                  : undefined,
              threadId: thread_id,
            },
          })
        }
        return
      }

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
            timestamp: eventTimestamp,
            data: { nodeId },
          },
        })
        return
      }

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
            timestamp: eventTimestamp,
            data: {
              nodeId,
              status: nodeData?.status || 'completed',
              duration: nodeData?.duration,
            },
          },
        })
        if (activeRequest) {
          dispatch({
            type: 'UPDATE_MESSAGE',
            id: activeRequest.aiMsgId,
            patch: { metadata: { lastNode: nodeLabel } },
          })
        }
        return
      }

      if (type === 'command') {
        const commandData = data as CommandEventData
        const stateUpdate = commandData?.update || {}
        dispatch({
          type: 'NODE_LOG',
          entry: {
            type: 'command',
            nodeName: node_name || 'unknown',
            timestamp: eventTimestamp,
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

      if (type === 'route_decision') {
        const decisionData = data as RouteDecisionEventData
        dispatch({
          type: 'NODE_LOG',
          entry: {
            type: 'route_decision',
            nodeName: decisionData?.node_id || 'unknown',
            timestamp: eventTimestamp,
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

      if (type === 'loop_iteration') {
        const iterationData = data as any
        dispatch({
          type: 'NODE_LOG',
          entry: {
            type: 'loop_iteration',
            nodeName: iterationData?.loop_node_id || 'unknown',
            timestamp: eventTimestamp,
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

      if (type === 'parallel_task') {
        const taskData = data as any
        dispatch({
          type: 'NODE_LOG',
          entry: {
            type: 'parallel_task',
            nodeName: 'system',
            timestamp: eventTimestamp,
            data: {
              taskId: taskData?.task_id,
              status: taskData?.status,
              result: taskData?.result,
              errorMsg: taskData?.error_msg,
            },
          },
        })
      }
    },
    [dispatch],
  )

  const connect = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    if (connectPromiseRef.current) return connectPromiseRef.current

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    cleanupSocket()

    connectPromiseRef.current = new Promise<void>((resolve, reject) => {
      connectResolveRef.current = resolve
      connectRejectRef.current = reject
    })

    try {
      const wsUrl = await getWsChatUrl()
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        reconnectAttemptsRef.current = 0
        connectResolveRef.current?.()
        connectPromiseRef.current = null
        connectResolveRef.current = null
        connectRejectRef.current = null

        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      ws.onmessage = (event) => {
        try {
          handleEvent(JSON.parse(event.data))
        } catch {
          // Ignore malformed frames
        }
      }

      ws.onclose = (event) => {
        setIsConnected(false)
        connectPromiseRef.current = null
        connectRejectRef.current?.(new Error(`socket closed: ${event.code}`))
        connectResolveRef.current = null
        connectRejectRef.current = null
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
          pingIntervalRef.current = null
        }

        if (event.code === 4001) {
          finalizeActiveRequests('Authentication expired')
          window.location.assign('/signin')
          return
        }

        if (Object.keys(activeRequestsRef.current).length > 0) {
          finalizeActiveRequests('Chat connection lost')
        }

        if (!isUnmountingRef.current && event.code !== 1000) {
          scheduleReconnect()
        }
      }

      ws.onerror = () => {
        setIsConnected(false)
      }

      return connectPromiseRef.current
    } catch (error) {
      connectPromiseRef.current = null
      connectResolveRef.current = null
      connectRejectRef.current = null
      throw error
    }
  }, [cleanupSocket, finalizeActiveRequests, handleEvent, scheduleReconnect])

  const ensureConnected = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    await connect()
  }, [connect])

  useEffect(() => {
    isUnmountingRef.current = false
    void connect()

    return () => {
      isUnmountingRef.current = true
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      cleanupSocket()
      finalizeActiveRequests('Chat session closed')
    }
  }, [cleanupSocket, connect, finalizeActiveRequests])

  const sendMessage = useCallback(
    async ({ message, threadId, graphId, metadata }: SendMessageOpts) => {
      if (!message.trim()) {
        throw new Error('Message cannot be empty')
      }

      const requestId = crypto.randomUUID()
      const aiMsgId = generateId()
      const initialAiMsg: Message = {
        id: aiMsgId,
        role: 'assistant',
        content: '',
        timestamp: now(),
        isStreaming: true,
        tool_calls: [],
      }

      dispatch({ type: 'APPEND_MESSAGE', message: initialAiMsg })
      dispatch({ type: 'CLEAR_INTERRUPT' })
      activeRequestsRef.current[requestId] = {
        aiMsgId,
        lastRunningToolIdByName: {},
      }
      if (threadId) {
        activeByThreadRef.current.set(threadId, requestId)
      }

      try {
        await ensureConnected()
        wsRef.current?.send(
          JSON.stringify({
            type: 'chat',
            request_id: requestId,
            thread_id: threadId || null,
            graph_id: graphId || null,
            message,
            metadata: metadata || {},
          }),
        )
        return { requestId }
      } catch (error) {
        delete activeRequestsRef.current[requestId]
        if (threadId) {
          activeByThreadRef.current.delete(threadId)
        }
        dispatch({ type: 'STREAM_ERROR', error: error instanceof Error ? error.message : 'Connection failed' })
        dispatch({ type: 'STREAM_DONE', messageId: aiMsgId })
        throw error
      }
    },
    [dispatch, ensureConnected],
  )

  const stopMessage = useCallback((threadId: string | null) => {
    if (!threadId) return
    const requestId = activeByThreadRef.current.get(threadId)
    if (!requestId || wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ type: 'stop', request_id: requestId }))
  }, [])

  const resumeChat = useCallback(
    async ({ threadId, command }: ResumeOpts) => {
      const requestId = crypto.randomUUID()
      const aiMsgId = generateId()
      const initialAiMsg: Message = {
        id: aiMsgId,
        role: 'assistant',
        content: '',
        timestamp: now(),
        isStreaming: true,
        tool_calls: [],
      }

      dispatch({ type: 'APPEND_MESSAGE', message: initialAiMsg })
      dispatch({ type: 'CLEAR_INTERRUPT' })
      activeRequestsRef.current[requestId] = {
        aiMsgId,
        lastRunningToolIdByName: {},
      }
      activeByThreadRef.current.set(threadId, requestId)

      try {
        await ensureConnected()
        wsRef.current?.send(
          JSON.stringify({
            type: 'resume',
            request_id: requestId,
            thread_id: threadId,
            command,
          }),
        )
        return { requestId }
      } catch (error) {
        delete activeRequestsRef.current[requestId]
        activeByThreadRef.current.delete(threadId)
        dispatch({ type: 'STREAM_ERROR', error: error instanceof Error ? error.message : 'Connection failed' })
        dispatch({ type: 'STREAM_DONE', messageId: aiMsgId })
        throw error
      }
    },
    [dispatch, ensureConnected],
  )

  return {
    isConnected,
    sendMessage,
    stopMessage,
    resumeChat,
  }
}

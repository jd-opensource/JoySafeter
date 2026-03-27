'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { generateUUID } from '@/lib/utils/uuid'
import { getChatWsClient } from '@/lib/ws/chat/chatWsClient'
import type { ChatSendInput, IncomingChatWsEvent, SkillCreatorExtension } from '@/lib/ws/chat/types'
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
  input: ChatSendInput
  threadId?: string | null
  graphId?: string | null
  extension?: SkillCreatorExtension | null
  metadata?: Record<string, unknown>
}

interface ResumeOpts {
  threadId: string
  command: { update?: Record<string, any>; goto?: string | null }
}

export interface UseChatWebSocketReturn {
  isConnected: boolean
  activeRequestId: string | null
  sendMessage: (opts: SendMessageOpts) => Promise<{ requestId: string }>
  stopMessage: (requestId: string | null) => void
  resumeChat: (opts: ResumeOpts) => Promise<{ requestId: string }>
}

export function useChatWebSocket(dispatch: React.Dispatch<ChatAction>): UseChatWebSocketReturn {
  const clientRef = useRef(getChatWsClient())
  const activeRequestsRef = useRef<Record<string, ActiveRequest>>({})
  const activeByThreadRef = useRef(new Map<string, string>())
  const activeThreadIdRef = useRef<string | null>(null)
  const currentRequestIdRef = useRef<string | null>(null)
  const [isConnected, setIsConnected] = useState(clientRef.current.getConnectionState().isConnected)
  const [activeRequestId, setActiveRequestIdState] = useState<string | null>(null)

  const setCurrentRequestId = useCallback((requestId: string | null) => {
    currentRequestIdRef.current = requestId
    setActiveRequestIdState(requestId)
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
      setCurrentRequestId(null)
    },
    [dispatch, setCurrentRequestId],
  )

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
          if (currentRequestIdRef.current === request_id) {
            setCurrentRequestId(null)
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
        if (request_id && currentRequestIdRef.current === request_id) {
          setCurrentRequestId(null)
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
        if (request_id && currentRequestIdRef.current === request_id) {
          setCurrentRequestId(null)
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
        if (request_id && currentRequestIdRef.current === request_id) {
          setCurrentRequestId(null)
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
    [dispatch, setCurrentRequestId],
  )

  useEffect(() => {
    const client = clientRef.current
    let prevConnected = client.getConnectionState().isConnected
    const unsubscribe = client.subscribeConnectionState((state) => {
      setIsConnected(state.isConnected)
      if (state.authExpired) {
        finalizeActiveRequests('Authentication expired')
        window.location.assign('/signin')
        return
      }
      if (prevConnected && !state.isConnected && Object.keys(activeRequestsRef.current).length > 0) {
        finalizeActiveRequests('Chat connection lost')
      }
      prevConnected = state.isConnected
    })
    void client.connect().catch(() => {
      setIsConnected(false)
    })

    return () => {
      unsubscribe()
      activeRequestsRef.current = {}
      activeByThreadRef.current.clear()
      activeThreadIdRef.current = null
    }
  }, [finalizeActiveRequests])

  const sendMessage = useCallback(
    async ({ input, threadId, graphId, extension, metadata }: SendMessageOpts) => {
      const requestId = generateUUID()
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
      setCurrentRequestId(requestId)
      activeRequestsRef.current[requestId] = {
        aiMsgId,
        lastRunningToolIdByName: {},
      }
      if (threadId) {
        activeByThreadRef.current.set(threadId, requestId)
      }

      try {
        const result = await clientRef.current.sendChat({
          requestId,
          input,
          extension,
          threadId,
          graphId,
          metadata,
          onEvent: (evt) => handleEvent(evt as IncomingChatWsEvent),
        })
        return { requestId: result.requestId }
      } catch (error) {
        const pending = activeRequestsRef.current[requestId]
        delete activeRequestsRef.current[requestId]
        if (currentRequestIdRef.current === requestId) {
          setCurrentRequestId(null)
        }
        if (threadId) {
          activeByThreadRef.current.delete(threadId)
        }
        if (pending) {
          const messageText = error instanceof Error ? error.message : 'Connection failed'
          dispatch({ type: 'STREAM_ERROR', error: messageText })
          dispatch({ type: 'STREAM_DONE', messageId: aiMsgId })
        }
        throw error
      }
    },
    [dispatch, handleEvent, setCurrentRequestId],
  )

  const stopMessage = useCallback((requestId: string | null) => {
    if (!requestId) return
    clientRef.current.stopByRequestId(requestId)
  }, [])

  const resumeChat = useCallback(
    async ({ threadId, command }: ResumeOpts) => {
      const requestId = generateUUID()
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
      setCurrentRequestId(requestId)
      activeRequestsRef.current[requestId] = {
        aiMsgId,
        lastRunningToolIdByName: {},
      }
      activeByThreadRef.current.set(threadId, requestId)

      try {
        const result = await clientRef.current.sendResume({
          requestId,
          threadId,
          command,
          onEvent: (evt) => handleEvent(evt as IncomingChatWsEvent),
        })
        return { requestId: result.requestId }
      } catch (error) {
        const pending = activeRequestsRef.current[requestId]
        delete activeRequestsRef.current[requestId]
        if (currentRequestIdRef.current === requestId) {
          setCurrentRequestId(null)
        }
        activeByThreadRef.current.delete(threadId)
        if (pending) {
          const messageText = error instanceof Error ? error.message : 'Connection failed'
          dispatch({ type: 'STREAM_ERROR', error: messageText })
          dispatch({ type: 'STREAM_DONE', messageId: aiMsgId })
        }
        throw error
      }
    },
    [dispatch, handleEvent, setCurrentRequestId],
  )

  return {
    isConnected,
    activeRequestId,
    sendMessage,
    stopMessage,
    resumeChat,
  }
}

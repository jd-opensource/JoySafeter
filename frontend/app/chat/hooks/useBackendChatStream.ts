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

import { Message, ToolCall } from '../types'

const generateId = () => Math.random().toString(36).substr(2, 9)

function now() {
  return Date.now()
}

export const useBackendChatStream = (
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
) => {
  const [isProcessing, setIsProcessing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const currentThreadIdRef = useRef<string | null>(null)
  const isMountedRef = useRef(true)

  // Helper function to safely update messages only if component is mounted
  const safeSetMessages = useCallback((updater: React.SetStateAction<Message[]>) => {
    if (isMountedRef.current) {
      setMessages(updater)
    }
  }, [setMessages])

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      // Abort any ongoing requests
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  const stopMessage = useCallback(async (threadId: string | null) => {
    // Use current threadId if provided, otherwise use the ref
    const targetThreadId = threadId || currentThreadIdRef.current
    
    // Always abort the fetch request first
    abortRef.current?.abort()
    
    if (!targetThreadId) {
      // If no threadId, just abort the current request
      setIsProcessing(false)
      return
    }

    try {
      // Call backend stop API using unified API client
      const { apiPost } = await import('@/lib/api-client')
      await apiPost('chat/stop', {
        thread_id: targetThreadId,
      })
      setIsProcessing(false)
    } catch (error) {
      console.error('Failed to stop chat:', error)
      // Fallback: we've already aborted the request
      setIsProcessing(false)
    }
  }, [])

  const sendMessage = useCallback(
    async (userPrompt: string, opts: { threadId?: string | null; graphId?: string | null; metadata?: Record<string, any> }) => {
      if (!userPrompt.trim()) return { threadId: opts.threadId || undefined }

      setIsProcessing(true)
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      const aiMsgId = generateId()
      const initialAiMsg: Message = {
        id: aiMsgId,
        role: 'assistant',
        content: '',
        timestamp: now(),
        isStreaming: true,
        tool_calls: [],
      }
      safeSetMessages((prev) => [...prev, initialAiMsg])

      // Map tool_name -> last running tool id in the UI (since backend doesn't emit ids)
      const lastRunningToolIdByName: Record<string, string> = {}
      // Track node execution for metadata
      const nodeExecutionLog: Array<{type: string, nodeName: string, timestamp: number, data?: any}> = []
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
            }

            // Handle thread_id event (initial handshake)
            if (type === 'thread_id') {
              return
            }

            // Handle content event (incremental text)
            if (type === 'content') {
              const contentData = data as ContentEventData
              const delta = contentData?.delta || ''
              if (!delta) return

              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      content: m.content + delta,
                      // Optional: save metadata for display
                      metadata: {
                        ...(m.metadata || {}),
                        lastNode: node_name,
                        lastRunId: run_id,
                        lastUpdate: timestamp,
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle tool_start event
            if (type === 'tool_start') {
              const toolData = data as ToolStartEventData
              const toolName = toolData?.tool_name || 'tool'
              const toolInput = toolData?.tool_input || {}
              const toolId = generateId()
              lastRunningToolIdByName[toolName] = toolId

              const tool: ToolCall = {
                id: toolId,
                name: toolName,
                args: toolInput,
                status: 'running',
                startTime: timestamp || now(),
              }

              safeSetMessages((prev) =>
                prev.map((m) =>
                  m.id === aiMsgId
                    ? { ...m, tool_calls: [...(m.tool_calls || []), tool] }
                    : m
                )
              )
              return
            }

            // Handle tool_end event
            if (type === 'tool_end') {
              const toolData = data as ToolEndEventData
              const toolName = toolData?.tool_name || 'tool'
              const toolOutput = toolData?.tool_output
              const toolId = lastRunningToolIdByName[toolName]

              if (!toolId) return

              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== aiMsgId) return m
                  const tools = (m.tool_calls || []).map((t) => {
                    if (t.id === toolId) {
                      return {
                        ...t,
                        status: 'completed' as const,
                        endTime: timestamp || now(),
                        result: toolOutput,
                      }
                    }
                    return t
                  })
                  return { ...m, tool_calls: tools }
                })
              )
              return
            }

            // Handle error event
            if (type === 'error') {
              const errorData = data as ErrorEventData
              const errorMsg = errorData?.message || 'Unknown error'
              
              // Check if this is a stop event
              if (errorMsg === 'Stream stopped' || errorMsg.includes('stopped')) {
                safeSetMessages((prev) =>
                  prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m))
                )
                return
              }

              safeSetMessages((prev) =>
                prev.map((m) =>
                  m.id === aiMsgId
                    ? { ...m, content: (m.content || '') + `\n\n*Error: ${errorMsg}*` }
                    : m
                )
              )
              return
            }

            // Handle done event
            if (type === 'done') {
              safeSetMessages((prev) =>
                prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m))
              )
              return
            }

            // Handle status event (optional, for displaying status information)
            if (type === 'status') {
              // Can display status information here, e.g., "Agent is thinking..."
              // Not handled for now, can be added as needed
              return
            }

            // Handle node_start event
            if (type === 'node_start') {
              const nodeData = data as NodeStartEventData
              const nodeLabel = nodeData?.node_label || node_name || 'Unknown Node'
              const nodeId = nodeData?.node_id || node_name

              nodeExecutionLog.push({
                type: 'node_start',
                nodeName: nodeLabel,
                timestamp,
                data: { nodeId }
              })

              // Update message metadata, display current executing node
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        currentNode: nodeLabel,
                        nodeExecutionLog: [...nodeExecutionLog],
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle node_end event
            if (type === 'node_end') {
              const nodeData = data as NodeEndEventData
              const nodeLabel = nodeData?.node_label || node_name || 'Unknown Node'
              const nodeId = nodeData?.node_id || node_name
              const status = nodeData?.status || 'completed'

              nodeExecutionLog.push({
                type: 'node_end',
                nodeName: nodeLabel,
                timestamp,
                data: { nodeId, status, duration: nodeData?.duration }
              })

              // Update message metadata
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        lastNode: nodeLabel,
                        nodeExecutionLog: [...nodeExecutionLog],
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle command event - contains node status update information
            if (type === 'command') {
              const commandData = data as CommandEventData

              // Record state update information
              const stateUpdate = commandData?.update || {}
              const hasStateChanges = Object.keys(stateUpdate).length > 0

              nodeExecutionLog.push({
                type: 'command',
                nodeName: node_name || 'unknown',
                timestamp,
                data: {
                  update: stateUpdate,
                  goto: commandData?.goto,
                  reason: commandData?.reason,
                  hasStateChanges
                }
              })

              // Update message metadata, including status change information
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        nodeExecutionLog: [...nodeExecutionLog],
                        lastStateUpdate: hasStateChanges ? stateUpdate : undefined,
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle route_decision event - routing decision information
            if (type === 'route_decision') {
              const decisionData = data as RouteDecisionEventData

              nodeExecutionLog.push({
                type: 'route_decision',
                nodeName: decisionData?.node_id || 'unknown',
                timestamp,
                data: {
                  nodeType: decisionData?.node_type,
                  result: decisionData?.result,
                  reason: decisionData?.reason,
                  goto: decisionData?.goto
                }
              })

              // Update message metadata, record routing decisions
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        nodeExecutionLog: [...nodeExecutionLog],
                        lastRouteDecision: {
                          nodeId: decisionData?.node_id,
                          result: decisionData?.result,
                          goto: decisionData?.goto,
                          reason: decisionData?.reason
                        },
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle loop_iteration event
            if (type === 'loop_iteration') {
              const iterationData = data as any // LoopIterationEventData

              nodeExecutionLog.push({
                type: 'loop_iteration',
                nodeName: iterationData?.loop_node_id || 'unknown',
                timestamp,
                data: {
                  iteration: iterationData?.iteration,
                  maxIterations: iterationData?.max_iterations,
                  conditionMet: iterationData?.condition_met,
                  reason: iterationData?.reason
                }
              })

              // Update message metadata
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        nodeExecutionLog: [...nodeExecutionLog],
                        lastLoopIteration: {
                          nodeId: iterationData?.loop_node_id,
                          iteration: iterationData?.iteration,
                          maxIterations: iterationData?.max_iterations,
                          conditionMet: iterationData?.condition_met
                        },
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle parallel_task event
            if (type === 'parallel_task') {
              const taskData = data as any // ParallelTaskEventData

              nodeExecutionLog.push({
                type: 'parallel_task',
                nodeName: 'system', // Parallel tasks are usually system-level
                timestamp,
                data: {
                  taskId: taskData?.task_id,
                  status: taskData?.status,
                  result: taskData?.result,
                  errorMsg: taskData?.error_msg
                }
              })

              // Update message metadata
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        nodeExecutionLog: [...nodeExecutionLog],
                      },
                    }
                  }
                  return m
                })
              )
              return
            }

            // Handle state_update event
            if (type === 'state_update') {
              const updateData = data as any // StateUpdateEventData

              // Update message metadata
              safeSetMessages((prev) =>
                prev.map((m) => {
                  if (m.id === aiMsgId) {
                    return {
                      ...m,
                      metadata: {
                        ...(m.metadata || {}),
                        lastStateUpdate: updateData?.state_snapshot,
                      },
                    }
                  }
                  return m
                })
              )
              return
            }
          },
        })

        if (result.threadId) {
          latestThreadId = result.threadId
          currentThreadIdRef.current = result.threadId
        }
      } catch (e: any) {
        const msg =
          e?.name === 'AbortError' ? 'Request cancelled' : `Error: ${String(e?.message || e)}`
        safeSetMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, content: (m.content || '') + `\n\n*${msg}*` } : m))
        )
      } finally {
        safeSetMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m))
        )
        if (isMountedRef.current) {
          setIsProcessing(false)
        }
      }

      return { threadId: latestThreadId }
    },
    [safeSetMessages]
  )

  return { sendMessage, stopMessage, isProcessing }
}

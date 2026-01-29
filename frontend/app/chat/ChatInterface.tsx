'use client'

import { List, Plus } from 'lucide-react'
import React, { useState, useEffect, useRef, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useDeployedGraphs, useWorkspaces } from '@/hooks/queries'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { conversationService } from '@/services/conversationService'

import ChatHome from './components/ChatHome'
import ChatInput from './components/ChatInput'
import ChatSidebar from './components/ChatSidebar'
import CompactToolStatus from './components/CompactToolStatus'
import ThreadContent from './components/ThreadContent'
import ToolExecutionPanel from './components/ToolExecutionPanel'
import { useBackendChatStream } from './hooks/useBackendChatStream'
import { graphResolutionService } from './services/graphResolutionService'
import { Message, ToolCall } from './types'

interface ChatInterfaceProps {
  chatId?: string | null
  onChatCreated?: (id: string) => void
  initialMessages?: Message[]
}

const generateId = () => Math.random().toString(36).substring(2, 11)

const ChatInterface: React.FC<ChatInterfaceProps> = ({
  chatId: propChatId,
  onChatCreated,
  initialMessages = [],
}) => {
  const { t } = useTranslation()
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  // We treat localChatId as the backend thread_id when using /chat/stream.
  const [localChatId, setLocalChatId] = useState<string | null>(propChatId || null)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevPropChatIdRef = useRef<string | null | undefined>(propChatId)
  const isInitialMountRef = useRef(true)

  // Data fetching for graph resolution
  const { data: deployedAgents = [] } = useDeployedGraphs()
  const { data: workspacesData } = useWorkspaces()

  // Sidebar visibility state
  const [sidebarVisible, setSidebarVisible] = useState(false)

  // Tool panel collapse state
  const [toolPanelOpen, setToolPanelOpen] = useState(false)

  // Selected tool for detailed view
  const [selectedTool, setSelectedTool] = useState<ToolCall | null>(null)

  // Agent status for streaming indicator
  const [agentStatus, setAgentStatus] = useState<'idle' | 'running' | 'connecting' | 'error'>('idle')
  const [streamingText, setStreamingText] = useState('')

  // Current mode state
  const [currentMode, setCurrentMode] = useState<string | undefined>(undefined)
  const [hasShownApkPrompt, setHasShownApkPrompt] = useState(false)
  // Current graphId state
  const [currentGraphId, setCurrentGraphId] = useState<string | null>(null)

  // Hook to handle real backend streaming via /chat/stream (SSE)
  const { sendMessage, stopMessage, isProcessing } = useBackendChatStream(setMessages)

  // Sync with props - only update when propChatId actually changes
  useEffect(() => {
    // Skip on initial mount to avoid unnecessary updates
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false
      return
    }

    // Check if propChatId actually changed
    if (propChatId !== prevPropChatIdRef.current) {
      prevPropChatIdRef.current = propChatId
      setLocalChatId(propChatId || null)
      setMessages(initialMessages)
    } else if (initialMessages.length > 0 && messages.length === 0) {
      // If we just loaded history into a fresh state
      setMessages(initialMessages)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propChatId])

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isProcessing])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+B to toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        setSidebarVisible(prev => !prev)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Check if there are any tool calls in the messages
  const hasToolCalls = messages.some(msg =>
    msg.tool_calls && msg.tool_calls.length > 0
  )

  // Extract all tool calls from messages
  const allToolCalls = messages.reduce<ToolCall[]>((acc, msg) => {
    if (msg.tool_calls) {
      return [...acc, ...msg.tool_calls]
    }
    return acc
  }, [])

  // Track previous tool calls count to detect new tool calls
  const prevToolCallsCountRef = useRef(0)

  // Auto-open tool panel when new tool calls are detected
  useEffect(() => {
    const currentToolCallsCount = allToolCalls.length
    const hasNewToolCalls = currentToolCallsCount > prevToolCallsCountRef.current

    if (hasNewToolCalls && currentToolCallsCount > 0 && !toolPanelOpen) {
      setToolPanelOpen(true)
    }

    prevToolCallsCountRef.current = currentToolCallsCount
  }, [allToolCalls.length, toolPanelOpen])

  // Handle conversation selection
  const handleSelectConversation = useCallback(async (threadId: string) => {
    setLocalChatId(threadId)
    setMessages([])
    setStreamingText('')
    setAgentStatus('idle')
    setSelectedTool(null)

    try {
      const backendMessages = await conversationService.getConversationHistory(threadId, {
        page: 1,
        pageSize: 100,
      })

      const formattedMessages: Message[] = backendMessages.map((msg) => {
        let toolCalls: ToolCall[] | undefined
        const toolCallsData = msg.metadata?.tool_calls
        if (Array.isArray(toolCallsData) && toolCallsData.length > 0) {
          toolCalls = toolCallsData.map((tc: any, index: number) => ({
            id: `tool-${msg.id}-${index}`,
            name: tc.name || 'unknown',
            args: tc.arguments || {},
            status: 'completed' as const,
            result: tc.output,
            startTime: new Date(msg.created_at).getTime(),
            endTime: new Date(msg.created_at).getTime(),
          }))
        }

        return {
          id: msg.id,
          role: msg.role as 'user' | 'assistant' | 'system',
          content: msg.content,
          tool_calls: toolCalls,
          timestamp: new Date(msg.created_at).getTime(),
        }
      })

      setMessages(formattedMessages)
    } catch (error) {
      console.error('Failed to load messages:', error)
      // If error, start with empty messages
      setMessages([])
    }
  }, [])

  // Handle new chat
  const handleNewChat = useCallback(() => {
    setMessages([])
    setLocalChatId(null)
    setSelectedTool(null)
    setStreamingText('')
    setAgentStatus('idle')
  }, [])

  // Handle tool click
  const handleToolClick = useCallback((toolCall: ToolCall) => {
    setSelectedTool(toolCall)
  }, [])

  // Auto-update localChatId when messages are added to a new conversation
  useEffect(() => {
    if (messages.length > 0 && !localChatId) {
      const id = generateId()
      setLocalChatId(id)
      if (onChatCreated) onChatCreated(id)
    }
  }, [messages, localChatId, onChatCreated])

  // Auto-show APK upload prompt when apk-vulnerability mode is detected
  useEffect(() => {
    if (
      currentMode === 'apk-vulnerability' &&
      messages.length === 0 &&
      !hasShownApkPrompt &&
      !isProcessing
    ) {
      setHasShownApkPrompt(true)
      const promptMessage: Message = {
        id: generateId(),
        role: 'assistant',
        content: t('chat.apkUploadPrompt', { defaultValue: '请上传 APK 文件以开始漏洞检测分析。' }),
        timestamp: Date.now(),
      }
      setMessages([promptMessage])
    }
  }, [currentMode, messages.length, hasShownApkPrompt, isProcessing, t])

  const handleSubmit = async (text: string, mode?: string, graphId?: string | null, files?: Array<{ id: string; filename: string; path: string; size: number }>) => {
    // Save mode and graphId state first (even if not submitting)
    if (mode) {
      setCurrentMode(mode)
    }
    if (graphId !== undefined) {
      setCurrentGraphId(graphId)
    }

    // Special case: if text is empty and mode is apk-vulnerability, just set mode and enter chat interface
    // Don't send message, let AI prompt user to upload APK
    if (!text.trim() && mode === 'apk-vulnerability' && (!files || files.length === 0)) {
      // Don't create a local chat ID here - let backend create conversation when first message is sent
      // This ensures the conversation exists in the backend before we try to use it
      return
    }

    // Allow submit if there's text OR if there are files (for APK auto-submit)
    if ((!text.trim() && (!files || files.length === 0)) || isProcessing) return

    // Resolve graphId if not provided and mode is set
    // Priority: 1. provided graphId, 2. saved currentGraphId, 3. resolve from mode
    let resolvedGraphId = graphId || currentGraphId
    if (!resolvedGraphId && mode) {
      const modeContext = {
        workspaces: workspacesData || [],
        deployedAgents,
        selectedAgentId: null,
        personalWorkspaceId: workspacesData?.find((w) => w.type === 'personal')?.id || null,
        t,
        router: { push: () => {} },
        queryClient: { invalidateQueries: () => {} },
      }
      const resolution = await graphResolutionService.resolve(mode, modeContext, false)
      resolvedGraphId = resolution.graphId
      // Save resolved graphId for future use
      if (resolvedGraphId) {
        setCurrentGraphId(resolvedGraphId)
      }
    }

    const userMsg: Message = {
      id: generateId(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }

    setMessages((prev) => [...prev, userMsg])
    setInput('') // Clear input immediately

    // Trigger AI stream - pass mode and files in metadata if needed
    // If localChatId doesn't exist in backend (i.e., it's a frontend-generated ID),
    // pass null to let backend create a new conversation
    // Only pass localChatId if we're certain it exists in backend (e.g., from conversation list)
    const messageOpts: { threadId?: string | null; graphId?: string | null; metadata?: Record<string, any> } = {
      threadId: localChatId || null, // Let backend create new conversation if localChatId is null
      graphId: resolvedGraphId || null,
    }
    if (mode) {
      messageOpts.metadata = { mode }
    }
    if (files && files.length > 0) {
      if (!messageOpts.metadata) {
        messageOpts.metadata = {}
      }
      messageOpts.metadata.files = files.map(f => ({
        filename: f.filename,
        path: f.path,
        size: f.size,
      }))
    }
    const result = await sendMessage(text, messageOpts)

    // Update localChatId if a new thread_id was returned from the backend
    if (result?.threadId && result.threadId !== localChatId) {
      setLocalChatId(result.threadId)
      // If this was a new conversation, notify parent component
      if (!localChatId && onChatCreated) {
        onChatCreated(result.threadId)
      }
    }
  }

  return (
    <div className="flex flex-col h-full w-full bg-gray-50 relative overflow-hidden">
      {/* Two-panel layout */}
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Left Sidebar - History (show/hide based on state) */}
        {sidebarVisible && (
          <>
            <ResizablePanel
              defaultSize={12}
              minSize={10}
              maxSize={25}
              className="transition-all duration-300"
            >
              <ChatSidebar
                isCollapsed={false}
                onToggle={() => setSidebarVisible(false)}
                onSelectConversation={handleSelectConversation}
                currentThreadId={localChatId}
                onNewChat={handleNewChat}
              />
            </ResizablePanel>

            <ResizableHandle className="w-px bg-gray-200" />
          </>
        )}

        {/* Main Panel - Chat */}
        <ResizablePanel defaultSize={88} minSize={70}>
          {/* If new chat and no messages, show ChatHome */}
          {messages.length === 0 && !localChatId && !propChatId ? (
            <div className="relative h-full flex flex-col overflow-hidden">
              {/* Header with Toggle Sidebar Button */}
              <div className={cn(
                "h-12 flex items-center gap-2 px-6 bg-gray-50 z-10 flex-shrink-0 transition-all duration-200"
              )}>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setSidebarVisible(prev => !prev)}
                        className="h-9 w-9 p-0 hover:bg-gray-100 transition-colors"
                      >
                        <List size={18} className="text-gray-600" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{sidebarVisible ? t('chat.hideHistory') : t('chat.showHistory')}</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleNewChat}
                        className="h-9 w-9 p-0 hover:bg-gray-100 transition-colors"
                      >
                        <Plus size={18} className="text-gray-600" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t('chat.newChat')}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <ChatHome
                onStartChat={handleSubmit}
                onSelectConversation={handleSelectConversation}
                isProcessing={isProcessing}
                onStop={() => stopMessage(localChatId)}
              />
            </div>
          ) : (
            <div className="relative h-full flex flex-col overflow-hidden">
              {/* Header */}
              <div className={cn(
                "h-12 flex items-center gap-2 px-6 bg-gray-50 z-10 flex-shrink-0 transition-all duration-200",
                toolPanelOpen && hasToolCalls && "pr-[632px]"
              )}>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setSidebarVisible(prev => !prev)}
                        className="h-9 w-9 p-0 hover:bg-gray-100 transition-colors"
                      >
                        <List size={18} className="text-gray-600" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{sidebarVisible ? t('chat.hideHistory') : t('chat.showHistory')}</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleNewChat}
                        className="h-9 w-9 p-0 hover:bg-gray-100 transition-colors"
                      >
                        <Plus size={18} className="text-gray-600" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t('chat.newChat')}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>

            {/* Messages - Scrollable area */}
            <div className={cn(
              "flex-1 min-h-0 overflow-hidden transition-all duration-200",
              toolPanelOpen && hasToolCalls && "mr-[616px]"
            )}>
              <ThreadContent
                messages={messages}
                streamingText={streamingText}
                agentStatus={agentStatus}
                onToolClick={handleToolClick}
                scrollContainerRef={scrollRef}
              />
            </div>

            {/* Input Area - Fixed at bottom */}
            <div className={cn(
              "flex-shrink-0 px-6 pb-6 pt-2 relative transition-all duration-200 bg-gray-50",
              toolPanelOpen && hasToolCalls && "pr-[632px]"
            )}>
              <ChatInput
                input={input}
                setInput={setInput}
                onSubmit={handleSubmit}
                isProcessing={isProcessing}
                onStop={() => stopMessage(localChatId)}
                currentMode={currentMode}
                currentGraphId={currentGraphId}
                compactToolStatus={
                  !toolPanelOpen && hasToolCalls ? (
                    <CompactToolStatus
                      toolCalls={allToolCalls}
                      onClick={() => setToolPanelOpen(true)}
                    />
                  ) : null
                }
              />
            </div>

            {/* Right Side Floating Panel - Tool Execution Panel */}
            {hasToolCalls && (
              <div
                className={cn(
                  'absolute top-4 right-4 bottom-4 bg-white border border-gray-200 shadow-2xl z-20 rounded-2xl overflow-hidden w-[600px]',
                  'transition-all duration-200',
                  toolPanelOpen
                    ? 'translate-x-0 translate-y-0 opacity-100 scale-100'
                    : 'translate-x-[-80%] translate-y-[30%] opacity-0 scale-[0.2] pointer-events-none'
                )}
                style={{
                  transitionTimingFunction: toolPanelOpen ? 'cubic-bezier(0, 0, 0.2, 1)' : 'cubic-bezier(0.4, 0, 1, 1)'
                }}
              >
                <ToolExecutionPanel
                  isOpen={toolPanelOpen}
                  onClose={() => setToolPanelOpen(false)}
                  toolCall={selectedTool}
                  messages={messages}
                  agentStatus={agentStatus}
                />
              </div>
            )}
            </div>
          )}
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

export default ChatInterface

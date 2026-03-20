'use client'

import { FolderOpen, List, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useDeployedGraphs, useWorkspaces } from '@/hooks/queries'
import { useAvailableModels } from '@/hooks/queries/models'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { conversationService } from '@/services/conversationService'

import ArtifactsDrawer from './components/ArtifactsDrawer'
import ChatHome from './components/ChatHome'
import ChatInput from './components/ChatInput'
import ChatSidebar from './components/ChatSidebar'
import CompactArtifactStatus from './components/CompactArtifactStatus'
import CompactToolStatus from './components/CompactToolStatus'
import ThreadContent from './components/ThreadContent'
import ToolExecutionPanel from './components/ToolExecutionPanel'
import { useBackendChatStream } from './hooks/useBackendChatStream'
import { graphResolutionService } from './services/graphResolutionService'
import { generateId, Message, ToolCall } from './types'

// ─── Layout constants ───────────────────────────────────────────────────────
const SIDE_PANEL_WIDTH = 600 // w-[600px]
const SIDE_PANEL_GAP = 16 // right-4 = 16px
const CONTENT_PR = SIDE_PANEL_WIDTH + SIDE_PANEL_GAP * 2 // 632
const CONTENT_MR = SIDE_PANEL_WIDTH + SIDE_PANEL_GAP // 616

interface ChatInterfaceProps {
  chatId?: string | null
  onChatCreated?: (id: string) => void
  initialMessages?: Message[]
}

const MODEL_SETUP_DISMISSED_KEY = 'modelSetupPromptDismissed'

export default function ChatInterface({
  chatId: propChatId,
  onChatCreated,
  initialMessages = [],
}: ChatInterfaceProps) {
  const { t } = useTranslation()
  const router = useRouter()
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
  const personalWorkspaceId = workspacesData?.find((w) => w.type === 'personal')?.id ?? null

  // Available models (for "no default model" notice); backend returns same list regardless of workspaceId
  const {
    data: availableModels = [],
    isSuccess: modelsLoaded,
    isError: modelsError,
  } = useAvailableModels('chat', { enabled: true })
  // No "usable" default: no model that is both default and available (has credentials)
  const hasNoDefaultModel =
    modelsLoaded &&
    !modelsError &&
    (availableModels.length === 0 ||
      !availableModels.some((m) => m.is_default === true && m.is_available === true))

  const [showNoDefaultModelNotice, setShowNoDefaultModelNotice] = useState(false)
  useEffect(() => {
    if (
      !personalWorkspaceId ||
      !hasNoDefaultModel ||
      typeof window === 'undefined' ||
      sessionStorage.getItem(MODEL_SETUP_DISMISSED_KEY) === '1'
    ) {
      return
    }
    setShowNoDefaultModelNotice(true)
  }, [personalWorkspaceId, hasNoDefaultModel])

  // Close modal if user configured a default model elsewhere (e.g. another tab)
  useEffect(() => {
    if (!hasNoDefaultModel && showNoDefaultModelNotice) {
      setShowNoDefaultModelNotice(false)
    }
  }, [hasNoDefaultModel, showNoDefaultModelNotice])

  // Sidebar visibility state
  const [sidebarVisible, setSidebarVisible] = useState(false)

  // Tool panel collapse state
  const [toolPanelOpen, setToolPanelOpen] = useState(false)

  // Selected tool for detailed view
  const [selectedTool, setSelectedTool] = useState<ToolCall | null>(null)

  // Optimistic "thinking" state: true from submit until hook sets isProcessing (avoids flash)
  const [submitting, setSubmitting] = useState(false)

  const [artifactDrawerOpen, setArtifactDrawerOpen] = useState(false)

  // Derive fileTree from the latest message that has one
  const fileTree = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const ft = messages[i].metadata?.fileTree as Record<string, any> | undefined
      if (ft && Object.keys(ft).length > 0) return ft
    }
    return undefined
  }, [messages])

  const hasFiles = !!fileTree && Object.keys(fileTree).length > 0

  // Hook to handle real backend streaming via /chat/stream (SSE) - must be before derived state
  const { sendMessage, stopMessage, isProcessing } = useBackendChatStream(setMessages)

  // Auto-open artifact drawer when files first appear
  const prevHasFilesRef = useRef(false)
  useEffect(() => {
    if (hasFiles && !prevHasFilesRef.current && !artifactDrawerOpen) {
      setToolPanelOpen(false)
      setArtifactDrawerOpen(true)
    }
    prevHasFilesRef.current = hasFiles
  }, [hasFiles])

  // Clear submitting once hook has taken over (isProcessing true)
  useEffect(() => {
    if (isProcessing) setSubmitting(false)
  }, [isProcessing])

  // Agent status: running when processing or optimistically when just submitted
  const agentStatus = useMemo<'idle' | 'running' | 'connecting' | 'error'>(
    () => (isProcessing || submitting ? 'running' : 'idle'),
    [isProcessing, submitting],
  )
  // Only treat last message as "current reply" when it is assistant (avoid showing previous round as streaming)
  const lastMsg = useMemo(() => messages[messages.length - 1], [messages])
  const streamingText = useMemo(() => {
    if (!lastMsg || lastMsg.role !== 'assistant') return ''
    if (!isProcessing && !lastMsg.isStreaming) return ''
    return lastMsg.content ?? ''
  }, [lastMsg, isProcessing])
  const currentNodeLabel = useMemo(
    () =>
      lastMsg?.role === 'assistant' ? (lastMsg.metadata?.currentNode ?? undefined) : undefined,
    [lastMsg],
  )

  // Current mode state
  const [currentMode, setCurrentMode] = useState<string | undefined>(undefined)
  const [hasShownApkPrompt, setHasShownApkPrompt] = useState(false)
  // Current graphId state
  const [currentGraphId, setCurrentGraphId] = useState<string | null>(null)

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

  // Auto-scroll to bottom after layout is complete (double rAF to avoid flash)
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      })
    })
    return () => cancelAnimationFrame(id)
  }, [messages, isProcessing])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+B to toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        setSidebarVisible((prev) => !prev)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Check if there are any tool calls in the messages
  const hasToolCalls = messages.some((msg) => msg.tool_calls && msg.tool_calls.length > 0)

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
    setSelectedTool(null)
    setArtifactDrawerOpen(false)

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
    // Navigate to base /chat to clear thread param and reset state via page prop update
    router.push('/chat')
    // We also clear local state immediately for perceived performance, though prop update will handle consistency
    setMessages([])
    setLocalChatId(null)
    setSelectedTool(null)
    setArtifactDrawerOpen(false)
    setCurrentMode(undefined)
    setHasShownApkPrompt(false)
    setCurrentGraphId(null)
  }, [router])

  // Handle tool click
  const handleToolClick = useCallback((toolCall: ToolCall) => {
    setSelectedTool(toolCall)
    setArtifactDrawerOpen(false)
    setToolPanelOpen(true)
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

  const handleSubmit = async (
    text: string,
    mode?: string,
    graphId?: string | null,
    files?: Array<{ id: string; filename: string; path: string; size: number }>,
  ) => {
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
    setSubmitting(true) // Show thinking card immediately to avoid flash

    // Trigger AI stream - pass mode and files in metadata if needed
    // If localChatId doesn't exist in backend (i.e., it's a frontend-generated ID),
    // pass null to let backend create a new conversation
    // Only pass localChatId if we're certain it exists in backend (e.g., from conversation list)
    const messageOpts: {
      threadId?: string | null
      graphId?: string | null
      metadata?: Record<string, any>
    } = {
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
      messageOpts.metadata.files = files.map((f) => ({
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

  // Whether the right side panel is visible (either tool or artifacts)
  const sidePanelVisible = (toolPanelOpen && hasToolCalls) || artifactDrawerOpen

  // ─── Shared sub-component: Header ─────────────────────────────────────────
  const renderHeader = (shrinkForPanel: boolean) => (
    <div
      className="z-10 flex h-12 flex-shrink-0 items-center gap-2 bg-gray-50 px-6 transition-all duration-200"
      style={shrinkForPanel && sidePanelVisible ? { paddingRight: CONTENT_PR } : undefined}
    >
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSidebarVisible((prev) => !prev)}
              className="h-9 w-9 p-0 transition-colors hover:bg-gray-100"
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
              className="h-9 w-9 p-0 transition-colors hover:bg-gray-100"
            >
              <Plus size={18} className="text-gray-600" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t('chat.newChat')}</p>
          </TooltipContent>
        </Tooltip>
        {localChatId && hasFiles && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setToolPanelOpen(false)
                  setArtifactDrawerOpen((v: boolean) => !v)
                }}
                className="h-9 w-9 p-0 transition-colors hover:bg-gray-100"
              >
                <FolderOpen size={18} className="text-gray-600" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>
                {artifactDrawerOpen
                  ? t('chat.closeArtifacts', { defaultValue: 'Close artifacts' })
                  : t('chat.openArtifacts', { defaultValue: 'Open artifacts' })}
              </p>
            </TooltipContent>
          </Tooltip>
        )}
      </TooltipProvider>
    </div>
  )

  // ─── Shared wrapper: Floating Side Panel ──────────────────────────────────
  const renderFloatingPanel = (isOpen: boolean, children: React.ReactNode) => (
    <div
      className={cn(
        'absolute bottom-4 right-4 top-4 z-20 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl',
        'transition-all duration-200',
        isOpen
          ? 'translate-x-0 translate-y-0 scale-100 opacity-100'
          : 'pointer-events-none translate-x-[-80%] translate-y-[30%] scale-[0.2] opacity-0',
      )}
      style={{
        width: SIDE_PANEL_WIDTH,
        transitionTimingFunction: isOpen
          ? 'cubic-bezier(0, 0, 0.2, 1)'
          : 'cubic-bezier(0.4, 0, 1, 1)',
      }}
    >
      {children}
    </div>
  )

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-gray-50">
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
            <div className="relative flex h-full flex-col overflow-hidden">
              {renderHeader(false)}
              <ChatHome
                onStartChat={handleSubmit}
                onSelectConversation={handleSelectConversation}
                isProcessing={isProcessing}
                onStop={() => stopMessage(localChatId)}
              />
            </div>
          ) : (
            <div className="relative flex h-full flex-col overflow-hidden">
              {renderHeader(true)}

              {/* Messages - Scrollable area */}
              <div
                className="flex min-h-0 flex-1 flex-col overflow-hidden transition-all duration-200"
                style={sidePanelVisible ? { marginRight: CONTENT_MR } : undefined}
              >
                <div className="min-h-0 flex-1 overflow-hidden">
                  <ThreadContent
                    messages={messages}
                    streamingText={streamingText}
                    agentStatus={agentStatus}
                    currentNodeLabel={currentNodeLabel}
                    onToolClick={handleToolClick}
                    scrollContainerRef={scrollRef}
                  />
                </div>
              </div>

              {/* Input Area - Fixed at bottom */}
              <div
                className="relative flex-shrink-0 bg-gray-50 px-6 pb-6 pt-2 transition-all duration-200"
                style={sidePanelVisible ? { paddingRight: CONTENT_PR } : undefined}
              >
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
                        onClick={() => {
                          setArtifactDrawerOpen(false)
                          setToolPanelOpen(true)
                        }}
                      />
                    ) : null
                  }
                  compactArtifactStatus={
                    !artifactDrawerOpen && localChatId && hasFiles ? (
                      <CompactArtifactStatus
                        onClick={() => {
                          setToolPanelOpen(false)
                          setArtifactDrawerOpen(true)
                        }}
                      />
                    ) : null
                  }
                />
              </div>

              {/* Right Side Floating Panel - Tool Execution Panel */}
              {hasToolCalls &&
                renderFloatingPanel(
                  toolPanelOpen,
                  <ToolExecutionPanel
                    isOpen={toolPanelOpen}
                    onClose={() => setToolPanelOpen(false)}
                    toolCall={selectedTool}
                    messages={messages}
                    agentStatus={agentStatus}
                  />,
                )}

              {/* Right Side Floating Panel - Artifacts Drawer */}
              {localChatId &&
                hasFiles &&
                renderFloatingPanel(
                  artifactDrawerOpen,
                  <ArtifactsDrawer
                    isOpen={artifactDrawerOpen}
                    onClose={() => setArtifactDrawerOpen(false)}
                    threadId={localChatId}
                    fileTree={fileTree}
                  />,
                )}
            </div>
          )}
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Important notice when no default model is configured */}
      <AlertDialog open={showNoDefaultModelNotice} onOpenChange={setShowNoDefaultModelNotice}>
        <AlertDialogContent hideCloseButton>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('chat.importantNotice')}</AlertDialogTitle>
            <AlertDialogDescription>{t('chat.noDefaultModelNotice')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                if (typeof window !== 'undefined') {
                  sessionStorage.setItem(MODEL_SETUP_DISMISSED_KEY, '1')
                }
                setShowNoDefaultModelNotice(false)
              }}
            >
              {t('chat.later')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (personalWorkspaceId) {
                  router.push('/settings/models')
                }
                setShowNoDefaultModelNotice(false)
              }}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {t('chat.goToModelSettings')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

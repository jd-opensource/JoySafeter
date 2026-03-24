'use client'

import { FolderOpen, List, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useEffect, useRef, useCallback } from 'react'
import type { ImperativePanelHandle } from 'react-resizable-panels'

import { Button } from '@/components/ui/button'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useDeployedGraphs, useWorkspaces } from '@/hooks/queries'
import { useTranslation } from '@/lib/i18n'
import { conversationService } from '@/services/conversationService'

import { useChatState, useChatStream } from './ChatProvider'
import ChatHome from './components/ChatHome'
import ChatSidebar from './components/ChatSidebar'
import { ModelNoticeDialog } from './components/ModelNoticeDialog'
import { getModeConfig } from './config/modeConfig'
import { ConversationPanel } from './conversation'
import { usePreviewTrigger } from './hooks/usePreviewTrigger'
import { PreviewPanel } from './preview'
import { graphResolutionService } from './services/graphResolutionService'
import { generateId, type Message, type ToolCall } from './types'

interface ChatLayoutProps {
  chatId?: string | null
}

export default function ChatLayout({ chatId: propChatId }: ChatLayoutProps) {
  const { state, dispatch } = useChatState()
  const stream = useChatStream()
  const { t } = useTranslation()
  const router = useRouter()

  // Data fetching
  const { data: deployedAgents = [] } = useDeployedGraphs()
  const { data: workspacesData } = useWorkspaces()

  usePreviewTrigger(state, dispatch)

  const prevPropChatIdRef = useRef<string | null | undefined>(propChatId)
  const isInitialMountRef = useRef(true)
  const sidebarPanelRef = useRef<ImperativePanelHandle>(null)
  const sidebarVisibleRef = useRef(state.ui.sidebarVisible)
  // eslint-disable-next-line react-hooks/refs
  sidebarVisibleRef.current = state.ui.sidebarVisible

  const toggleSidebar = useCallback(() => {
    if (sidebarVisibleRef.current) {
      sidebarPanelRef.current?.collapse()
    } else {
      sidebarPanelRef.current?.expand()
    }
  }, [])

  // Keyboard shortcut: Cmd+B toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        toggleSidebar()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [toggleSidebar])

  // Sync propChatId changes
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false
      if (propChatId) {
        dispatch({ type: 'SET_THREAD', threadId: propChatId })
      }
      return
    }

    if (propChatId !== prevPropChatIdRef.current) {
      prevPropChatIdRef.current = propChatId
      if (propChatId) {
        dispatch({ type: 'SET_THREAD', threadId: propChatId })
      } else {
        dispatch({ type: 'RESET' })
      }
    }
  }, [propChatId, dispatch])

  // APK auto-prompt
  useEffect(() => {
    if (
      state.mode.currentMode === 'apk-vulnerability' &&
      state.messages.length === 0 &&
      !state.mode.hasShownApkPrompt &&
      !stream.isProcessing
    ) {
      dispatch({ type: 'SET_APK_PROMPT_SHOWN' })
      const promptMessage: Message = {
        id: generateId(),
        role: 'assistant',
        content: t('chat.apkUploadPrompt', { defaultValue: '请上传 APK 文件以开始漏洞检测分析。' }),
        timestamp: Date.now(),
      }
      dispatch({ type: 'APPEND_MESSAGE', message: promptMessage })
    }
  }, [state.mode.currentMode, state.messages.length, state.mode.hasShownApkPrompt, stream.isProcessing, t, dispatch])

  // Handle conversation selection from sidebar
  const handleSelectConversation = useCallback(
    async (threadId: string) => {
      dispatch({ type: 'SET_THREAD', threadId })
      dispatch({ type: 'SET_MESSAGES', messages: [] })
      dispatch({ type: 'SELECT_TOOL', tool: null })

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

        dispatch({ type: 'SET_MESSAGES', messages: formattedMessages })
      } catch (error) {
        console.error('Failed to load messages:', error)
        dispatch({ type: 'SET_MESSAGES', messages: [] })
      }
    },
    [dispatch],
  )

  // Handle new chat
  const handleNewChat = useCallback(() => {
    router.push('/chat')
    dispatch({ type: 'RESET' })
  }, [router, dispatch])

  // Handle message submit
  const handleSubmit = useCallback(
    async (
      text: string,
      mode?: string,
      graphId?: string | null,
      files?: Array<{ id: string; filename: string; path: string; size: number }>,
    ) => {
      // Save mode state
      if (mode) {
        dispatch({ type: 'SET_MODE', mode, graphId: graphId || null })
      } else if (graphId !== undefined) {
        dispatch({
          type: 'SET_MODE',
          mode: state.mode.currentMode || '',
          graphId: graphId || null,
        })
      }

      // APK special case: empty text just sets mode
      if (!text.trim() && mode === 'apk-vulnerability' && (!files || files.length === 0)) {
        return
      }

      if ((!text.trim() && (!files || files.length === 0)) || stream.isProcessing) return

      // Resolve graphId
      let resolvedGraphId = graphId || state.mode.currentGraphId
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
        if (resolvedGraphId) {
          dispatch({
            type: 'SET_MODE',
            mode: mode || state.mode.currentMode || '',
            graphId: resolvedGraphId,
          })
        }
      }

      // Add user message
      const userMsg: Message = {
        id: generateId(),
        role: 'user',
        content: text,
        timestamp: Date.now(),
      }
      dispatch({ type: 'APPEND_MESSAGE', message: userMsg })
      dispatch({ type: 'SET_INPUT', value: '' })
      dispatch({ type: 'STREAM_START' })

      // Build opts
      const messageOpts: {
        threadId?: string | null
        graphId?: string | null
        metadata?: Record<string, any>
      } = {
        threadId: state.threadId || null,
        graphId: resolvedGraphId || null,
      }
      if (mode) {
        messageOpts.metadata = { mode }
      }
      if (files && files.length > 0) {
        if (!messageOpts.metadata) messageOpts.metadata = {}
        messageOpts.metadata.files = files.map((f) => ({
          filename: f.filename,
          path: f.path,
          size: f.size,
        }))
      }

      try {
        await stream.sendMessage({
          message: text,
          threadId: messageOpts.threadId,
          graphId: messageOpts.graphId,
          metadata: messageOpts.metadata,
        })
      } catch (error) {
        console.error('Failed to send chat message:', error)
      }
    },
    [dispatch, stream, state.threadId, state.mode, workspacesData, deployedAgents, t],
  )

  const handleStop = useCallback(() => {
    stream.stopMessage(state.threadId)
  }, [stream, state.threadId])

  const hasFiles = Object.keys(state.preview.fileTree).length > 0
  const hasMessages = state.messages.length > 0 || !!state.threadId || !!propChatId

  // ─── Header ──────────────────────────────────────────────────────────────
  const headerTitle = (state.mode.currentMode && getModeConfig(state.mode.currentMode)?.labelKey) || 'chat.defaultChat'
  const renderHeader = () => (
    <div className="z-10 flex h-14 flex-shrink-0 items-center gap-2 border-b border-gray-100 bg-white px-6">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleSidebar}
              className="h-9 w-9 rounded-lg p-0 transition-colors hover:bg-gray-100"
            >
              <List size={18} className="text-gray-600" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{state.ui.sidebarVisible ? t('chat.hideHistory') : t('chat.showHistory')}</p>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleNewChat}
              className="h-9 w-9 rounded-full bg-blue-600 p-0 text-white transition-colors hover:bg-blue-700"
            >
              <Plus size={18} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t('chat.newChat')}</p>
          </TooltipContent>
        </Tooltip>
        <div className="flex min-w-0 flex-1 justify-center">
          <span className="truncate text-sm font-medium text-gray-700">
            {t(headerTitle)}
          </span>
        </div>
        {state.threadId && hasFiles && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (state.preview.visible) {
                    dispatch({ type: 'HIDE_PREVIEW' })
                  } else {
                    dispatch({ type: 'SHOW_PREVIEW' })
                  }
                }}
                className="h-9 w-9 rounded-lg p-0 transition-colors hover:bg-gray-100"
              >
                <FolderOpen size={18} className="text-gray-600" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>
                {state.preview.visible
                  ? t('chat.closeArtifacts', { defaultValue: 'Close artifacts' })
                  : t('chat.openArtifacts', { defaultValue: 'Open artifacts' })}
              </p>
            </TooltipContent>
          </Tooltip>
        )}
      </TooltipProvider>
    </div>
  )

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-gray-50">
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Left Sidebar */}
        <ResizablePanel
          ref={sidebarPanelRef}
          defaultSize={0}
          minSize={10}
          maxSize={25}
          collapsible
          collapsedSize={0}
          onCollapse={() => dispatch({ type: 'SET_SIDEBAR_VISIBLE', visible: false })}
          onExpand={() => dispatch({ type: 'SET_SIDEBAR_VISIBLE', visible: true })}
          className="overflow-hidden transition-all duration-300"
        >
          <ChatSidebar
            isCollapsed={!state.ui.sidebarVisible}
            onToggle={toggleSidebar}
            onSelectConversation={handleSelectConversation}
            currentThreadId={state.threadId}
          />
        </ResizablePanel>
        <ResizableHandle className="w-px bg-gray-200" />

        {/* Main Panel */}
        <ResizablePanel defaultSize={state.preview.visible ? 55 : 88} minSize={40}>
          <div className="relative flex h-full flex-col overflow-hidden">
            {renderHeader()}
            {!hasMessages ? (
              <ChatHome
                onStartChat={handleSubmit}
                onSelectConversation={handleSelectConversation}
                isProcessing={stream.isProcessing}
                onStop={handleStop}
              />
            ) : (
              <ConversationPanel onSend={handleSubmit} onStop={handleStop} />
            )}
          </div>
        </ResizablePanel>

        {/* Preview Panel */}
        {state.preview.visible && (
          <>
            <ResizableHandle className="w-px bg-gray-200" />
            <ResizablePanel defaultSize={45} minSize={30} maxSize={60}>
              <PreviewPanel />
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>

      <ModelNoticeDialog />
    </div>
  )
}

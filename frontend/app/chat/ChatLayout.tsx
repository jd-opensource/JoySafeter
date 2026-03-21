'use client'

import { FolderOpen, List, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useEffect, useRef, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useDeployedGraphs, useWorkspaces } from '@/hooks/queries'
import { useTranslation } from '@/lib/i18n'
import { conversationService } from '@/services/conversationService'

import ChatHome from './components/ChatHome'
import ChatSidebar from './components/ChatSidebar'
import { ModelNoticeDialog } from './components/ModelNoticeDialog'
import { ConversationPanel } from './conversation'
import { PreviewPanel } from './preview'
import { useChatState, useChatStream } from './ChatProvider'
import { useBackendChatStream } from './hooks/useBackendChatStream'
import { usePreviewTrigger } from './hooks/usePreviewTrigger'
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

  // Hook integrations
  const { sendMessage, stopMessage } = useBackendChatStream(dispatch)
  usePreviewTrigger(state, dispatch)

  const prevPropChatIdRef = useRef<string | null | undefined>(propChatId)
  const isInitialMountRef = useRef(true)

  // Keyboard shortcut: Cmd+B toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        dispatch({ type: 'TOGGLE_SIDEBAR' })
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [dispatch])

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

      const result = await sendMessage(text, messageOpts)

      // Update threadId from backend
      if (result?.threadId && result.threadId !== state.threadId) {
        dispatch({ type: 'SET_THREAD', threadId: result.threadId })
      }
    },
    [dispatch, sendMessage, stream.isProcessing, state.threadId, state.mode, workspacesData, deployedAgents, t],
  )

  const handleStop = useCallback(() => {
    stopMessage(state.threadId)
  }, [stopMessage, state.threadId])

  const hasFiles = Object.keys(state.preview.fileTree).length > 0
  const hasMessages = state.messages.length > 0 || !!state.threadId || !!propChatId

  // ─── Header ──────────────────────────────────────────────────────────────
  const renderHeader = () => (
    <div className="z-10 flex h-12 flex-shrink-0 items-center gap-2 bg-gray-50 px-6">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
              className="h-9 w-9 p-0 transition-colors hover:bg-gray-100"
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
              className="h-9 w-9 p-0 transition-colors hover:bg-gray-100"
            >
              <Plus size={18} className="text-gray-600" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t('chat.newChat')}</p>
          </TooltipContent>
        </Tooltip>
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
                className="h-9 w-9 p-0 transition-colors hover:bg-gray-100"
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
        {state.ui.sidebarVisible && (
          <>
            <ResizablePanel
              defaultSize={12}
              minSize={10}
              maxSize={25}
              className="transition-all duration-300"
            >
              <ChatSidebar
                isCollapsed={false}
                onToggle={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
                onSelectConversation={handleSelectConversation}
                currentThreadId={state.threadId}
                onNewChat={handleNewChat}
              />
            </ResizablePanel>
            <ResizableHandle className="w-px bg-gray-200" />
          </>
        )}

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

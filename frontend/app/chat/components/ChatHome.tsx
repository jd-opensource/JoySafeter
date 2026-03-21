'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  MessageSquare,
  ArrowRight,
  X,
  ChevronDown,
  Square,
  Loader2,
  Sparkles,
  Zap,
  Paperclip,
  Bot,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useRef, useEffect, useMemo } from 'react'

import { type AgentGraph } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useDeployedGraphs, useWorkspaces } from '@/hooks/queries'
import { API_BASE, apiUpload } from '@/lib/api-client'
import {
  isAllowedFile,
  ALLOWED_EXTENSIONS_STRING,
  UPLOAD_LIMITS,
} from '@/lib/constants/upload-limits'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError } from '@/lib/utils/toast'

import { modeConfigs } from '../config/modeConfig'
import { useChatSession } from '../hooks/useChatSession'
import { chatModeService } from '../services/chatModeService'
import { copilotRedirectService } from '../services/copilotRedirectService'
import { graphResolutionService } from '../services/graphResolutionService'
import { registerAllHandlers } from '../services/modeHandlers/registerHandlers'
import { StarterPrompts } from '../shared/StarterPrompts'
import type { UploadedFile, ModeSelectionResult } from '../services/modeHandlers/types'

// Register all mode handlers (executed once when module loads)
if (typeof window !== 'undefined') {
  registerAllHandlers()
}

interface ChatHomeProps {
  onStartChat: (
    message: string,
    mode?: string,
    graphId?: string | null,
    files?: UploadedFile[],
  ) => void
  onSelectConversation?: (threadId: string) => void
  isProcessing?: boolean
  onStop?: () => void
}

export default function ChatHome({
  onStartChat,
  onSelectConversation,
  isProcessing = false,
  onStop,
}: ChatHomeProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()

  // Use unified state management
  const {
    state,
    setInput,
    addFile,
    removeFile,
    setMode,
    clearMode,
    setSelectedAgentId,
    setAutoRedirect,
    setIsRedirecting,
    setShowCases,
    setIsUploading,
    resetInput,
  } = useChatSession()

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const hasInitializedDefaultMode = useRef(false)

  // Derive starter prompts from current mode
  const starterPrompts = useMemo(() => {
    if (!state.mode.type) return null
    const config = modeConfigs.find((c) => c.id === state.mode.type)
    return config?.starterPrompts && config.starterPrompts.length > 0 ? config.starterPrompts : null
  }, [state.mode.type])

  // Data fetching
  const { data: deployedAgents = [], isLoading: isLoadingAgents } = useDeployedGraphs()
  const { data: workspacesData } = useWorkspaces()

  // Build mode context
  const modeContext = {
    workspaces: workspacesData || [],
    deployedAgents,
    selectedAgentId: state.selectedAgentId,
    personalWorkspaceId: workspacesData?.find((w) => w.type === 'personal')?.id || null,
    t,
    router,
    queryClient,
  }

  // Build mode options (generated from config, ensuring config is the single source of truth)
  const modeOptions = modeConfigs.map((config) => {
    const handler = chatModeService.getHandler(config.id)
    // Use config as data source, handler only for business logic
    return {
      id: config.id,
      label: t(config.labelKey),
      description: t(config.descriptionKey),
      icon: config.icon,
      type: config.type,
      templateName: config.templateName,
      templateGraphName: config.templateGraphName,
      handler, // Used to execute mode-related business logic
    }
  })

  // Auto-adjust textarea height
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
    }
  }, [state.input])

  // File upload handling
  const handleFileUpload = async (file: File) => {
    const validation = isAllowedFile(file)
    if (!validation.allowed) {
      toastError(
        validation.reason || t('chat.fileNotAllowed', { defaultValue: '文件不符合要求' }),
        t('chat.fileUploadFailed'),
      )
      return
    }

    setIsUploading(true)
    try {
      const fileData = await apiUpload<{
        filename: string
        path: string
        size: number
        message: string
      }>(`${API_BASE}/files/upload`, file)

      if (fileData && fileData.filename) {
        const uploadedFile: UploadedFile = {
          id: Date.now().toString(),
          filename: fileData.filename,
          path: fileData.path,
          size: fileData.size,
        }
        addFile(uploadedFile)
        toastSuccess(fileData.filename, t('chat.fileUploaded'))
      } else {
        toastError(
          t('chat.uploadFailed', { defaultValue: '上传失败，响应格式异常' }),
          t('chat.fileUploadFailed'),
        )
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error
          ? error.message
          : typeof error === 'string'
            ? error
            : t('chat.retry', { defaultValue: '请重试' })
      toastError(errorMessage, t('chat.fileUploadFailed'))
    } finally {
      setIsUploading(false)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      if (files.length > UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD) {
        toastError(
          t('chat.tooManyFiles', {
            defaultValue: '最多只能同时上传 {{maxFiles}} 个文件',
            maxFiles: UPLOAD_LIMITS.MAX_FILES_PER_UPLOAD,
          }),
          t('chat.fileUploadFailed'),
        )
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
        return
      }
      Array.from(files).forEach((file) => {
        handleFileUpload(file)
      })
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // Handle mode selection
  const handleModeSelect = async (modeId: string): Promise<ModeSelectionResult | null> => {
    const handler = chatModeService.getHandler(modeId)
    if (!handler) {
      console.warn(`No handler found for mode: ${modeId}`)
      return null
    }

    setIsRedirecting(true)
    try {
      const result = await handler.onSelect(modeContext)
      if (result.success) {
        // Apply state updates
        if (result.stateUpdates) {
          if (result.stateUpdates.input !== undefined) {
            setInput(result.stateUpdates.input)
          }
          if (result.stateUpdates.mode !== undefined || result.stateUpdates.graphId !== undefined) {
            setMode({
              type: result.stateUpdates.mode || modeId,
              graphId: result.stateUpdates.graphId,
            })
          }
        } else {
          // If no special handling, just set the mode
          setMode({ type: modeId })
        }
        return result
      } else if (result.error) {
        toastError(
          result.error,
          t('chat.modeSelectionFailed', { defaultValue: 'Mode selection failed' }),
        )
        return result
      }
      return null
    } catch (error) {
      console.error('Failed to select mode:', error)
      const errorMessage =
        error instanceof Error
          ? error.message
          : t('chat.modeSelectionFailed', { defaultValue: 'Mode selection failed' })
      toastError(errorMessage, t('chat.retry', { defaultValue: 'Please try again' }))
      return null
    } finally {
      setIsRedirecting(false)
    }
  }

  // Default chat: auto-select default-chat mode on first load (create_deep_agent + skills + Docker)
  useEffect(() => {
    if (
      hasInitializedDefaultMode.current ||
      state.mode.type != null ||
      !modeContext.personalWorkspaceId ||
      isProcessing
    ) {
      return
    }
    hasInitializedDefaultMode.current = true
    handleModeSelect('default-chat').catch(() => {
      hasInitializedDefaultMode.current = false
    })
  }, [state.mode.type, modeContext.personalWorkspaceId, isProcessing])

  // Handle submission
  const handleSubmit = async () => {
    if (!state.input.trim() || isProcessing || state.isRedirecting) return

    const currentMode = state.mode.type
    const handler = currentMode ? chatModeService.getHandler(currentMode) : null

    // Validation
    if (handler?.validate) {
      const validation = handler.validate(state.input, state.files)
      if (!validation.valid) {
        // Translate error message if it's a translation key
        const errorMessage =
          validation.error || t('chat.validationFailed', { defaultValue: 'Validation failed' })
        toastError(errorMessage, t('chat.submitFailed', { defaultValue: 'Submit failed' }))
        return
      }
    }

    // Process input and files
    let processedInput = state.input.trim()
    let graphId: string | null = null

    if (handler) {
      try {
        const submitResult = await handler.onSubmit(state.input, state.files, modeContext)
        if (!submitResult.success) {
          toastError(
            submitResult.error || t('chat.submitFailed', { defaultValue: 'Submit failed' }),
            t('chat.submitFailed', { defaultValue: 'Submit failed' }),
          )
          return
        }
        processedInput = submitResult.processedInput || processedInput
        graphId = submitResult.graphId || null
      } catch (error) {
        console.error('Failed to process submit:', error)
        toastError(
          error instanceof Error
            ? error.message
            : t('chat.submitFailed', { defaultValue: 'Submit failed' }),
          t('chat.submitFailed', { defaultValue: 'Submit failed' }),
        )
        return
      }
    } else {
      // No mode handler, use Graph resolution service
      const resolution = await graphResolutionService.resolve(
        currentMode,
        modeContext,
        state.autoRedirect,
      )
      graphId = resolution.graphId
    }

    // If auto redirect is enabled
    if (state.autoRedirect) {
      const success = await copilotRedirectService.executeRedirect(processedInput, modeContext)
      if (success) {
        resetInput()
        return
      }
    }

    // Clear input and call onStartChat
    resetInput()
    onStartChat(
      processedInput,
      currentMode || undefined,
      graphId,
      state.files.length > 0 ? state.files : undefined,
    )
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Handle mode card click
  const handleCaseClick = async (modeId: string, isSelected: boolean) => {
    const mode = modeOptions.find((m) => m.id === modeId)
    if (!mode) return

    // Special handling for Skill Creator mode - navigate to dedicated page
    if (modeId === 'skill-creator') {
      router.push('/skills/creator')
      return
    }

    // Special handling for APK vulnerability mode - initialize graph first
    if (modeId === 'apk-vulnerability') {
      // Use handleModeSelect to initialize graph if needed
      const result = await handleModeSelect(modeId)
      if (result?.success) {
        // Get graphId from result or state
        const graphId = result.stateUpdates?.graphId || state.mode.graphId
        // After initialization, enter chat page with the graphId
        onStartChat('', modeId, graphId)
      }
      // If initialization failed, error is already shown by handleModeSelect
      return
    }

    // If already selected, deselect
    if (isSelected) {
      clearMode()
      setSelectedAgentId(null)
      return
    }

    // Select new mode
    setSelectedAgentId(null)
    await handleModeSelect(modeId)
  }

  // Handle agent selection
  const handleAgentSelect = (agentId: string) => {
    setAutoRedirect(false)
    setSelectedAgentId(agentId)
    clearMode()
  }

  return (
    <div className="flex h-full w-full bg-gray-50">
      <div className="relative flex flex-1 flex-col items-center justify-center p-8">
        <div className="flex w-full max-w-3xl flex-col gap-8">
          <div className="text-center">
            <h1 className="mb-2 text-4xl font-light tracking-tight text-gray-900">
              {t('chat.createSomethingAwesome')}
            </h1>
          </div>

          <div className="relative mx-auto w-full max-w-4xl">
            <div className="rounded-2xl border border-gray-200 bg-gray-50 transition-all">
              <div className="flex w-full flex-col gap-2 px-4 py-3">
                {state.selectedAgentId &&
                  (() => {
                    const selectedAgent = deployedAgents.find(
                      (a: AgentGraph) => a.id === state.selectedAgentId,
                    )
                    return selectedAgent ? (
                      <div className="flex items-center gap-2 px-3 pt-2">
                        <div className="flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1.5 text-sm font-medium text-gray-700">
                          <MessageSquare size={14} />
                          <span className="max-w-[120px] truncate">{selectedAgent.name}</span>
                          <button
                            onClick={() => setSelectedAgentId(null)}
                            className="ml-1 rounded-full p-0.5 transition-colors hover:bg-gray-200"
                            aria-label={t('chat.clearAgent')}
                          >
                            <X size={12} />
                          </button>
                        </div>
                      </div>
                    ) : null
                  })()}

                <div className="flex items-end gap-3 px-3">
                  <div className="relative flex flex-1 flex-col gap-1">
                    <input
                      type="file"
                      ref={fileInputRef}
                      onChange={handleFileSelect}
                      multiple
                      accept={ALLOWED_EXTENSIONS_STRING}
                      className="hidden"
                      disabled={isProcessing || state.isUploading}
                    />
                    {state.files.length > 0 && (
                      <div className="flex flex-wrap gap-2 px-1 pb-1 pt-2">
                        {state.files.map((file) => (
                          <div
                            key={file.id}
                            className="flex items-center gap-1.5 rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-700"
                          >
                            <Paperclip size={12} className="text-gray-500" />
                            <span className="max-w-[150px] truncate">{file.filename}</span>
                            <button
                              onClick={() => removeFile(file.id)}
                              className="ml-1 rounded-full p-0.5 transition-colors hover:bg-gray-200"
                              aria-label="Remove file"
                            >
                              <X size={10} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                    <textarea
                      ref={textareaRef}
                      value={state.input}
                      onChange={handleInputChange}
                      onKeyDown={handleKeyDown}
                      placeholder={t('chat.describeHelpNeeded')}
                      className="max-h-[160px] min-h-[24px] w-full resize-none overflow-y-auto border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none focus-visible:ring-0"
                      rows={1}
                      disabled={isProcessing}
                    />
                    <div className="absolute bottom-1 left-1 flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => !state.isRedirecting && setAutoRedirect(!state.autoRedirect)}
                        disabled={state.isRedirecting}
                        className={cn(
                          'flex h-9 items-center gap-2 rounded-full border-[1.5px] bg-transparent px-3 transition-all duration-200',
                          state.autoRedirect
                            ? 'border-emerald-200 text-emerald-600 hover:border-emerald-300 hover:bg-emerald-50'
                            : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:bg-gray-50 hover:text-gray-700',
                        )}
                      >
                        <Zap size={16} />
                        <span className="text-sm font-medium">
                          {state.autoRedirect ? t('chat.agentModeOn') : t('chat.agentModeOff')}
                        </span>
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="outline"
                            size="sm"
                            className="flex h-9 items-center gap-2 rounded-full border-[1.5px] border-gray-200 bg-transparent px-3 text-gray-500 transition-all duration-200 hover:border-gray-300 hover:bg-gray-50 hover:text-gray-700"
                            disabled={isLoadingAgents}
                          >
                            <Bot size={16} />
                            <span className="text-sm font-medium">{t('chat.selectAgent')}</span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="start"
                          className="max-h-[300px] w-56 overflow-y-auto"
                        >
                          {isLoadingAgents ? (
                            <DropdownMenuItem disabled>{t('chat.loading')}...</DropdownMenuItem>
                          ) : deployedAgents.length === 0 ? (
                            <DropdownMenuItem disabled>
                              {t('chat.noDeployedAgents')}
                            </DropdownMenuItem>
                          ) : (
                            <>
                              {deployedAgents.map((agent: AgentGraph) => (
                                <DropdownMenuItem
                                  key={agent.id}
                                  onClick={() => handleAgentSelect(agent.id)}
                                  className={cn(
                                    'flex items-center gap-2',
                                    state.selectedAgentId === agent.id && 'bg-gray-100',
                                  )}
                                >
                                  <MessageSquare size={14} className="text-gray-400" />
                                  <span className="flex-1 truncate">{agent.name}</span>
                                  {state.selectedAgentId === agent.id && (
                                    <span className="text-xs text-gray-400">✓</span>
                                  )}
                                </DropdownMenuItem>
                              ))}
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    <TooltipProvider delayDuration={100}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={isProcessing || state.isUploading}
                            className={cn(
                              'flex h-8 w-8 items-center justify-center rounded-xl border-[1.5px] border-gray-200 bg-transparent p-0 text-gray-500 transition-all duration-200 hover:bg-gray-50 hover:text-gray-700',
                              state.isUploading && 'cursor-not-allowed opacity-50',
                            )}
                          >
                            {state.isUploading ? (
                              <Loader2 size={18} className="animate-spin" />
                            ) : (
                              <Paperclip size={18} />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          {t('chat.uploadFile')}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    {isProcessing && onStop ? (
                      <Button
                        onClick={onStop}
                        size="sm"
                        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-red-500 p-0 transition-all hover:bg-red-600"
                        title={t('chat.stop')}
                      >
                        <Square size={14} className="fill-white text-white" />
                      </Button>
                    ) : (
                      <Button
                        onClick={handleSubmit}
                        disabled={!state.input.trim() || isProcessing || state.isRedirecting}
                        size="sm"
                        className={cn(
                          'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full p-0 transition-all',
                          state.input.trim() && !isProcessing && !state.isRedirecting
                            ? 'bg-blue-600 hover:bg-blue-700'
                            : 'cursor-not-allowed bg-gray-100',
                        )}
                      >
                        {state.isRedirecting ? (
                          <Loader2 size={18} className="animate-spin text-gray-400" />
                        ) : (
                          <ArrowRight
                            size={18}
                            className={
                              state.input.trim() && !isProcessing && !state.isRedirecting
                                ? 'text-white'
                                : 'text-gray-300'
                            }
                          />
                        )}
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 w-full">
            <button
              onClick={() => setShowCases(!state.showCases)}
              className="flex w-full items-center justify-between p-2 text-sm font-medium text-gray-500 transition-colors hover:text-gray-700"
            >
              <div className="flex items-center gap-2">
                <Sparkles size={14} />
                <span>{t('chat.exploreAgentModeCases')}</span>
              </div>
              <ChevronDown
                size={14}
                className={cn('transition-transform duration-300', state.showCases && 'rotate-180')}
              />
            </button>

            <div
              className={cn(
                'grid grid-cols-2 gap-3 overflow-hidden transition-all duration-500 ease-in-out',
                state.showCases ? 'mt-4 max-h-[500px] opacity-100' : 'max-h-0 opacity-0',
              )}
            >
              {modeOptions.map((mode) => {
                const isSelected = state.mode.type === mode.id
                const Icon = mode.icon
                return (
                  <div
                    key={mode.id}
                    onClick={() => handleCaseClick(mode.id, isSelected)}
                    className={cn(
                      'group flex cursor-pointer items-start gap-4 overflow-hidden rounded-xl border bg-white p-4 transition-all duration-200',
                      isSelected
                        ? 'border-blue-500 bg-blue-50 shadow-md ring-1 ring-blue-100'
                        : 'border-gray-200 hover:border-blue-200 hover:shadow-lg',
                    )}
                  >
                    <div className="rounded-lg border border-blue-100 bg-blue-50 p-2">
                      <Icon
                        size={20}
                        className={cn(isSelected ? 'text-blue-600' : 'text-gray-600')}
                      />
                    </div>
                    <div>
                      <h3
                        className={cn(
                          'text-sm font-medium',
                          isSelected ? 'text-blue-700' : 'text-gray-800 group-hover:text-blue-700',
                        )}
                      >
                        {mode.label}
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">{mode.description}</p>
                    </div>
                  </div>
                )
              })}
            </div>

            {starterPrompts && (
              <div className="mt-4">
                <StarterPrompts
                  prompts={starterPrompts}
                  onSelect={(prompt) => setInput(prompt)}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

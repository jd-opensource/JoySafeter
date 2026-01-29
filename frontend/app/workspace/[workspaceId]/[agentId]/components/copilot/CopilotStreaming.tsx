/**
 * CopilotStreaming - Streaming content display component
 */

import { Sparkles, Loader2, Check, Copy, ChevronDown, ChevronUp } from 'lucide-react'
import React from 'react'

import type { StageType } from '@/hooks/copilot/useCopilotStreaming'
import { useTranslation } from '@/lib/i18n'

interface CopilotStreamingProps {
  loading: boolean
  currentStage: { stage: StageType; message: string } | null
  streamingContent: string
  currentToolCall: { tool: string; input: Record<string, unknown> } | null
  toolResults: Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  expandedToolTypes: Set<string>
  copiedStreaming: boolean
  streamingContentRef: React.RefObject<HTMLDivElement | null>
  stageConfig: Record<StageType, { icon: string; color: string; label: string }>
  onToggleToolType: (type: string) => void
  onCopyStreaming: () => void
}

export function CopilotStreaming({
  loading,
  currentStage,
  streamingContent,
  currentToolCall,
  toolResults,
  expandedToolTypes,
  copiedStreaming,
  streamingContentRef,
  stageConfig,
  onToggleToolType,
  onCopyStreaming,
}: CopilotStreamingProps) {
  const { t } = useTranslation()

  if (!loading && !currentStage && !streamingContent && toolResults.length === 0) return null

  // Group tool results by type
  const grouped = toolResults.reduce((acc, result, idx) => {
    if (!acc[result.type]) {
      acc[result.type] = []
    }
    acc[result.type].push({ ...result, originalIndex: idx })
    return acc
  }, {} as Record<string, Array<{ type: string; payload: Record<string, unknown>; reasoning?: string; originalIndex: number }>>)

  // Get sorted types (to maintain order)
  const types = Object.keys(grouped).sort((a, b) => {
    const aFirstIdx = grouped[a][0].originalIndex
    const bFirstIdx = grouped[b][0].originalIndex
    return aFirstIdx - bFirstIdx
  })

  return (
    <div className="flex gap-2">
      <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 shadow-sm bg-gradient-to-br from-purple-100 to-blue-50 text-purple-600 border border-purple-100">
        <Sparkles size={16} />
      </div>
      <div className="flex flex-col gap-2 max-w-[85%]">
        {/* Status stage display - show default if loading but no stage set */}
        {(currentStage || loading) && (
          <div className="bg-gradient-to-r from-purple-50 to-blue-50 rounded-2xl rounded-bl-none p-3 border border-purple-100/50 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-base">
                {currentStage ? (stageConfig[currentStage.stage]?.icon || '⏳') : '⏳'}
              </span>
              <span
                className={`text-xs font-medium ${currentStage ? (stageConfig[currentStage.stage]?.color || 'text-gray-600') : 'text-gray-600'}`}
              >
                {currentStage?.message || '正在处理中...'}
              </span>
              <Loader2 size={12} className="animate-spin text-purple-500" />
            </div>
            {/* Progress bar */}
            <div className="mt-2 h-1 bg-purple-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-purple-400 to-blue-400 rounded-full transition-all duration-500 ease-out animate-pulse"
                style={{
                  width: currentStage?.stage === 'processing' ? '90%' : currentStage?.stage === 'generating' ? '70%' : '30%',
                }}
              />
            </div>
          </div>
        )}

        {/* Streaming content display with tool call info integrated */}
        {(streamingContent || currentToolCall) && (
          <div className={`rounded-2xl rounded-bl-none border shadow-sm animate-in fade-in duration-200 overflow-hidden ${
            streamingContent
              ? 'bg-white border-gray-100'
              : 'bg-amber-50 border-amber-200'
          }`}>
            {/* Tool call info - fixed at top, always visible */}
            {currentToolCall && (
              <div className={`p-2.5 shrink-0 ${
                streamingContent ? 'bg-amber-50 border-b border-amber-200/50' : ''
              }`}>
                <div className="flex items-center gap-2">
                  <Loader2 size={12} className="animate-spin text-amber-600 shrink-0" />
                  <span className="text-[10px] font-medium text-amber-700">
                    {t('workspace.callingTool') || 'Calling Tool'}:
                  </span>
                  <span className="text-[10px] font-mono font-bold text-amber-900 truncate">
                    {currentToolCall.tool}
                  </span>
                </div>
                {Object.keys(currentToolCall.input).length > 0 && (
                  <div className="mt-1.5 text-[9px] font-mono text-amber-800/70 bg-amber-100/50 rounded px-2 py-1 max-h-16 overflow-y-auto">
                    {JSON.stringify(currentToolCall.input, null, 2)}
                  </div>
                )}
              </div>
            )}
            {/* Streaming content - scrollable area below tool call */}
            {streamingContent && (
              <div className="relative group">
                {/* Copy button */}
                <button
                  onClick={onCopyStreaming}
                  className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded hover:bg-gray-100 z-10"
                  title="复制"
                >
                  {copiedStreaming ? (
                    <Check size={12} className="text-green-600" />
                  ) : (
                    <Copy size={12} className="text-gray-500" />
                  )}
                </button>
                {/* Scrollable content */}
                <div
                  ref={streamingContentRef}
                  className="p-3 pr-5 max-h-64 overflow-y-auto custom-scrollbar"
                >
                  <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap break-words">
                    {streamingContent}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tool results display - grouped by type with collapse */}
        {toolResults.length > 0 && (
          <div className="bg-green-50 rounded-xl border border-green-200 p-2 space-y-1.5 animate-in fade-in duration-200">
            <div className="flex items-center gap-1.5 text-[10px] font-bold text-green-700 uppercase tracking-wider px-1">
              <Check size={10} /> {t('workspace.toolResults') || 'Tool Results'}
            </div>
            {types.map((type) => {
              const results = grouped[type]
              const isExpanded = expandedToolTypes.has(type)
              const hasMultiple = results.length > 1
              const visibleResults = hasMultiple && !isExpanded ? [results[results.length - 1]] : results
              const hiddenCount = hasMultiple && !isExpanded ? results.length - 1 : 0

              return (
                <div key={type} className="space-y-1">
                  {visibleResults.map((result, idx) => (
                    <div
                      key={`${type}-${result.originalIndex}`}
                      className="flex items-center gap-2 bg-white/60 p-1.5 rounded-lg border border-green-100/50"
                    >
                      <div className="w-4 h-4 rounded-full bg-green-100 text-green-600 flex items-center justify-center shrink-0">
                        <Check size={8} strokeWidth={4} />
                      </div>
                      <div className="flex flex-col min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono font-medium text-green-900">
                            {result.type}
                          </span>
                          {hasMultiple && !isExpanded && idx === visibleResults.length - 1 && (
                            <span className="text-[9px] text-green-600 font-medium bg-green-100/50 px-1.5 py-0.5 rounded">
                              {results.length} 项
                            </span>
                          )}
                        </div>
                        {result.reasoning && (
                          <span className="text-[9px] text-green-700 line-clamp-2 mt-0.5">
                            {result.reasoning}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                  {hiddenCount > 0 && (
                    <button
                      onClick={() => onToggleToolType(type)}
                      className="flex items-center gap-1.5 text-[9px] text-green-600 hover:text-green-700 hover:bg-green-100/50 px-2 py-1 rounded transition-colors w-full text-left"
                    >
                      <ChevronDown size={10} />
                      <span>展开 {hiddenCount} 个已折叠的 {type} 操作</span>
                    </button>
                  )}
                  {isExpanded && hasMultiple && (
                    <button
                      onClick={() => onToggleToolType(type)}
                      className="flex items-center gap-1.5 text-[9px] text-green-600 hover:text-green-700 hover:bg-green-100/50 px-2 py-1 rounded transition-colors w-full text-left"
                    >
                      <ChevronUp size={10} />
                      <span>折叠 {results.length - 1} 个 {type} 操作</span>
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

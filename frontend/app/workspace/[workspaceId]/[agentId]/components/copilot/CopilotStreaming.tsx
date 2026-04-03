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
  const grouped = toolResults.reduce(
    (acc, result, idx) => {
      if (!acc[result.type]) {
        acc[result.type] = []
      }
      acc[result.type].push({ ...result, originalIndex: idx })
      return acc
    },
    {} as Record<
      string,
      Array<{
        type: string
        payload: Record<string, unknown>
        reasoning?: string
        originalIndex: number
      }>
    >,
  )

  // Get sorted types (to maintain order)
  const types = Object.keys(grouped).sort((a, b) => {
    const aFirstIdx = grouped[a][0].originalIndex
    const bFirstIdx = grouped[b][0].originalIndex
    return aFirstIdx - bFirstIdx
  })

  return (
    <div className="flex gap-2">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--brand-200)] bg-gradient-to-br from-[var(--brand-100)] to-[var(--brand-50)] text-[var(--brand-600)] shadow-sm">
        <Sparkles size={16} />
      </div>
      <div className="flex max-w-[85%] flex-col gap-2">
        {/* Status stage display - show default if loading but no stage set */}
        {(currentStage || loading) && (
          <div className="rounded-2xl rounded-bl-none border border-purple-100/50 bg-gradient-to-r from-purple-50 to-blue-50 p-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-base">
                {currentStage ? stageConfig[currentStage.stage]?.icon || '⏳' : '⏳'}
              </span>
              <span
                className={`text-xs font-medium ${currentStage ? stageConfig[currentStage.stage]?.color || 'text-[var(--text-tertiary)]' : 'text-[var(--text-tertiary)]'}`}
              >
                {(currentStage && stageConfig[currentStage.stage]?.label) || t('workspace.processing', { defaultValue: 'Processing...' })}
              </span>
              <Loader2 size={12} className="animate-spin text-purple-500" />
            </div>
            {/* Progress bar */}
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-purple-100">
              <div
                className="h-full animate-pulse rounded-full bg-gradient-to-r from-purple-400 to-blue-400 transition-all duration-500 ease-out"
                style={{
                  width:
                    currentStage?.stage === 'processing'
                      ? '90%'
                      : currentStage?.stage === 'generating'
                        ? '70%'
                        : '30%',
                }}
              />
            </div>
          </div>
        )}

        {/* Streaming content display with tool call info integrated */}
        {(streamingContent || currentToolCall) && (
          <div
            className={`overflow-hidden rounded-2xl rounded-bl-none border shadow-sm duration-200 animate-in fade-in ${
              streamingContent ? 'border-[var(--border-muted)] bg-[var(--surface-elevated)]' : 'border-amber-200 bg-amber-50'
            }`}
          >
            {/* Tool call info - fixed at top, always visible */}
            {currentToolCall && (
              <div
                className={`shrink-0 p-2.5 ${
                  streamingContent ? 'border-b border-amber-200/50 bg-amber-50' : ''
                }`}
              >
                <div className="flex items-center gap-2">
                  <Loader2 size={12} className="shrink-0 animate-spin text-amber-600" />
                  <span className="text-[10px] font-medium text-amber-700">
                    {t('workspace.callingTool') || 'Calling Tool'}:
                  </span>
                  <span className="truncate font-mono text-[10px] font-bold text-amber-900">
                    {currentToolCall.tool}
                  </span>
                </div>
                {Object.keys(currentToolCall.input).length > 0 && (
                  <div className="mt-1.5 max-h-16 overflow-y-auto rounded bg-amber-100/50 px-2 py-1 font-mono text-[9px] text-amber-800/70">
                    {JSON.stringify(currentToolCall.input, null, 2)}
                  </div>
                )}
              </div>
            )}
            {/* Streaming content - scrollable area below tool call */}
            {streamingContent && (
              <div className="group relative">
                {/* Copy button */}
                <button
                  onClick={onCopyStreaming}
                  className="absolute right-1 top-1 z-10 rounded p-1.5 opacity-0 transition-opacity hover:bg-[var(--surface-3)] group-hover:opacity-100"
                  title="复制"
                >
                  {copiedStreaming ? (
                    <Check size={12} className="text-green-600" />
                  ) : (
                    <Copy size={12} className="text-[var(--text-tertiary)]" />
                  )}
                </button>
                {/* Scrollable content */}
                <div
                  ref={streamingContentRef}
                  className="custom-scrollbar max-h-64 overflow-y-auto p-3 pr-5"
                >
                  <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--text-secondary)]">
                    {streamingContent}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tool results display - grouped by type with collapse */}
        {toolResults.length > 0 && (
          <div className="space-y-1.5 rounded-xl border border-green-200 bg-green-50 p-2 duration-200 animate-in fade-in">
            <div className="flex items-center gap-1.5 px-1 text-[10px] font-bold uppercase tracking-wider text-green-700">
              <Check size={10} /> {t('workspace.toolResults') || 'Tool Results'}
            </div>
            {types.map((type) => {
              const results = grouped[type]
              const isExpanded = expandedToolTypes.has(type)
              const hasMultiple = results.length > 1
              const visibleResults =
                hasMultiple && !isExpanded ? [results[results.length - 1]] : results
              const hiddenCount = hasMultiple && !isExpanded ? results.length - 1 : 0

              return (
                <div key={type} className="space-y-1">
                  {visibleResults.map((result, idx) => (
                    <div
                      key={`${type}-${result.originalIndex}`}
                      className="flex items-center gap-2 rounded-lg border border-green-100/50 bg-white/60 p-1.5"
                    >
                      <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-green-100 text-green-600">
                        <Check size={8} strokeWidth={4} />
                      </div>
                      <div className="flex min-w-0 flex-1 flex-col">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] font-medium text-green-900">
                            {result.type}
                          </span>
                          {hasMultiple && !isExpanded && idx === visibleResults.length - 1 && (
                            <span className="rounded bg-green-100/50 px-1.5 py-0.5 text-[9px] font-medium text-green-600">
                              {results.length} 项
                            </span>
                          )}
                        </div>
                        {result.reasoning && (
                          <span className="mt-0.5 line-clamp-2 text-[9px] text-green-700">
                            {result.reasoning}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                  {hiddenCount > 0 && (
                    <button
                      onClick={() => onToggleToolType(type)}
                      className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[9px] text-green-600 transition-colors hover:bg-green-100/50 hover:text-green-700"
                    >
                      <ChevronDown size={10} />
                      <span>
                        展开 {hiddenCount} 个已折叠的 {type} 操作
                      </span>
                    </button>
                  )}
                  {isExpanded && hasMultiple && (
                    <button
                      onClick={() => onToggleToolType(type)}
                      className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[9px] text-green-600 transition-colors hover:bg-green-100/50 hover:text-green-700"
                    >
                      <ChevronUp size={10} />
                      <span>
                        折叠 {results.length - 1} 个 {type} 操作
                      </span>
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

/**
 * CopilotInput - Input area and toolbar component
 */

import { Send, Sparkles, Square, RotateCcw, PlusCircle, LayoutGrid } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'

const SUGGESTION_CHIP_KEYS = ['workspace.copilotChipAddAgent'] as const

interface CopilotInputProps {
  input: string
  loading: boolean
  executingActions: boolean
  messagesCount: number
  onInputChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  onReset: () => void
  onAIDecision: () => void
  /** Send a message directly (e.g. when clicking a suggestion chip) */
  onSendWithText?: (text: string) => void
  /** Default model label from settings for status bar */
  modelLabel?: string
}

export function CopilotInput({
  input,
  loading,
  executingActions,
  messagesCount,
  onInputChange,
  onSend,
  onStop,
  onReset,
  onAIDecision,
  onSendWithText,
  modelLabel,
}: CopilotInputProps) {
  const { t } = useTranslation()
  const canSendChip = !loading && !executingActions && !!onSendWithText

  const chipBase =
    'flex-shrink-0 text-[11px] px-2.5 py-1 rounded-full transition flex items-center gap-1 whitespace-nowrap'

  return (
    <div className="flex-shrink-0 px-1 py-0 bg-white/90 backdrop-blur border-t border-gray-100">
      {/* Suggestion chips + AI 自动完善 in one row */}
      <div className="flex gap-1.5 overflow-x-auto pb-1.5 mb-0.5 no-scrollbar items-center min-h-0">
        {/* AI 自动完善 - same chip container, purple accent */}
        <button
          type="button"
          onClick={onAIDecision}
          disabled={loading || executingActions || messagesCount <= 1}
          className={`${chipBase} border border-purple-200 bg-purple-50/50 text-purple-700 hover:bg-purple-100 hover:border-purple-300 disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          <Sparkles size={10} className="text-purple-500 shrink-0" />
          {t('workspace.aiDecision')}
        </button>
        {canSendChip &&
          SUGGESTION_CHIP_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onSendWithText?.(t(key))}
              className={`${chipBase} bg-gray-100 hover:bg-gray-200 border border-gray-200 text-gray-700`}
            >
              <PlusCircle size={10} className="text-purple-500 shrink-0" />
              {t(key)}
            </button>
          ))}
        {/* Reset at end of row when there is history */}
        {messagesCount > 1 && (
          <span className="ml-auto flex-shrink-0">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={onReset}
                    disabled={loading}
                    className="w-6 h-6 rounded-full flex items-center justify-center bg-gray-100 hover:bg-gray-200 border border-gray-200 text-gray-500 hover:text-gray-700 disabled:opacity-50 transition"
                  >
                    <RotateCcw size={12} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs">
                  {t('workspace.resetConversation')}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </span>
        )}
      </div>

      {/* Input Container */}
      <div className="relative shadow-sm rounded-xl flex gap-2">
        <input
          className="w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 text-xs focus:outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-100/50 transition-all"
          placeholder={t('workspace.describeFlowChanges')}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !loading && onSend()}
          disabled={loading || executingActions}
        />
        {loading ? (
          <Button
            variant="default"
            size="icon"
            onClick={onStop}
            className="!bg-red-600 hover:!bg-red-700"
          >
            <Square size={14} fill="currentColor" />
          </Button>
        ) : (
          <Button
            variant="default"
            size="icon"
            onClick={onSend}
            disabled={executingActions || !input.trim()}
            className="!bg-purple-600 hover:!bg-purple-700"
          >
            <Send size={14} />
          </Button>
        )}
      </div>
      {/* Status bar: Mode + default model */}
      <div className="mt-2 flex justify-between items-center px-1 text-[10px] text-gray-500">
        <span className="flex items-center gap-1">
          <LayoutGrid size={10} className="shrink-0" />
          {t('workspace.copilotStatusMode')}
        </span>
        <span>{modelLabel ?? t('workspace.copilotStatusModelPlaceholder')}</span>
      </div>
    </div>
  )
}

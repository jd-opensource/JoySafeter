/**
 * CopilotInput - Input area and toolbar component
 */

import { Send, Sparkles, Square, RotateCcw } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'

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
}: CopilotInputProps) {
  const { t } = useTranslation()

  return (
    <div className="flex-shrink-0 px-1 py-0 bg-white/90 backdrop-blur border-t border-gray-100">
      {/* Toolbar - Above Input */}
      <div className="flex items-center justify-between mb-1">
        {/* Left: AI Decision Capsule */}
        <Button
          variant="outline"
          size="sm"
          onClick={onAIDecision}
          disabled={loading || executingActions || messagesCount <= 1}
          className="h-5 px-1.5 text-[9px] rounded-full border-purple-200 bg-purple-50/50 text-purple-700 hover:bg-purple-100 hover:border-purple-300 hover:text-purple-800 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Sparkles size={9} className="mr-0.5" />
          {t('workspace.aiDecision')}
        </Button>

        {/* Right: Reset Button (only show when there's conversation history) */}
        {messagesCount > 1 && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onReset}
                  disabled={loading}
                  className="h-7 w-7 text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                >
                  <RotateCcw size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                {t('workspace.resetConversation')}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
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
    </div>
  )
}

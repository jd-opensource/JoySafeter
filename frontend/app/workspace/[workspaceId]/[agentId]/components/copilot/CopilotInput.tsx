/**
 * CopilotInput - Input area and toolbar component
 */

import { Send, Sparkles, Square, RotateCcw, LayoutGrid } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'

export type CopilotMode = 'standard' | 'deepagents'

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
  /** Build mode: single agent vs DeepAgents */
  copilotMode: CopilotMode
  onModeChange: (mode: CopilotMode) => void
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
  onSendWithText: _onSendWithText,
  copilotMode,
  onModeChange,
  modelLabel,
}: CopilotInputProps) {
  const { t } = useTranslation()

  const chipBase =
    'flex-shrink-0 text-[11px] px-2.5 py-1 rounded-full transition flex items-center gap-1 whitespace-nowrap'

  return (
    <div className="flex-shrink-0 border-t border-[var(--border-muted)] bg-[var(--surface-elevated)] px-1 py-0 backdrop-blur">
      {/* AI 自动完善 + Mode selection in one row */}
      <div className="mb-0.25 no-scrollbar flex min-h-0 items-center gap-1 overflow-x-auto pb-0.5">
        <button
          type="button"
          onClick={onAIDecision}
          disabled={loading || executingActions || messagesCount <= 1}
          className={`${chipBase} border border-purple-200 bg-purple-50/50 text-purple-600 hover:border-purple-300 hover:bg-purple-100 disabled:cursor-not-allowed disabled:opacity-50`}
        >
          <Sparkles size={10} className="shrink-0 text-purple-500" />
          {t('workspace.aiDecision')}
        </button>
        <div className="flex-shrink-0">
          <Select
            value={copilotMode}
            onValueChange={(value) => onModeChange(value as CopilotMode)}
            disabled={loading || executingActions}
          >
            <SelectTrigger className="h-6 min-w-[5rem] max-w-[5.5rem] border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text-secondary)]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="standard" className="text-xs">
                {t('workspace.copilotModeSingleAgent')}
              </SelectItem>
              <SelectItem value="deepagents" className="text-xs">
                {t('workspace.copilotModeDeepAgents')}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        {/* Reset 放置在最右侧 */}
        {messagesCount > 1 && (
          <span className="ml-auto flex-shrink-0">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={onReset}
                    disabled={loading}
                    className="flex h-6 w-6 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-3)] text-[var(--text-tertiary)] transition hover:bg-[var(--surface-5)] hover:text-[var(--text-secondary)] disabled:opacity-50"
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
      <div className="relative flex gap-2 rounded-xl shadow-sm">
        <input
          className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-2.5 text-xs transition-all focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/10"
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
            className="!bg-[var(--status-error)] hover:!bg-[var(--status-error-hover)]"
          >
            <Square size={14} fill="currentColor" />
          </Button>
        ) : (
          <Button
            variant="default"
            size="icon"
            onClick={onSend}
            disabled={executingActions || !input.trim()}
            className="!bg-primary hover:!bg-primary/90"
          >
            <Send size={14} />
          </Button>
        )}
      </div>
      {/* Status bar: Mode + default model */}
      <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-[var(--text-tertiary)]">
        <span className="flex items-center gap-1">
          <LayoutGrid size={10} className="shrink-0" />
          {t('workspace.copilotStatusMode')}
        </span>
        <span>{modelLabel ?? t('workspace.copilotStatusModelPlaceholder')}</span>
      </div>
    </div>
  )
}

'use client'

import { useState } from 'react'
import { ChevronDown, Send, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

interface CopilotOverlayProps {
  agentId: string
  expanded: boolean
  onToggle: () => void
}

export function CopilotOverlay({ agentId, expanded, onToggle }: CopilotOverlayProps) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')

  if (!expanded) {
    return (
      <div className="absolute bottom-2 left-1/2 z-30 w-full max-w-xl -translate-x-1/2 px-4">
        <button
          className="flex w-full items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)]/90 px-4 py-2.5 text-sm text-[var(--text-muted)] shadow-lg backdrop-blur transition-colors hover:bg-[var(--surface-2)]"
          onClick={onToggle}
        >
          <Sparkles className="h-4 w-4 shrink-0 text-[var(--skill-brand-600)]" />
          {t('graph.copilot.placeholder', {
            defaultValue: 'Ask Copilot to build or modify your graph...',
          })}
        </button>
      </div>
    )
  }

  return (
    <div className="absolute bottom-2 left-1/2 z-30 flex h-[40vh] w-full max-w-2xl -translate-x-1/2 flex-col rounded-xl border border-[var(--border)] bg-[var(--surface-1)] shadow-2xl">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <Sparkles className="h-3.5 w-3.5 text-[var(--skill-brand-600)]" />
          Copilot
        </span>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onToggle}>
          <ChevronDown className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <p className="text-center text-xs text-[var(--text-muted)]">
          {t('graph.copilot.empty', {
            defaultValue: 'Ask Copilot to add nodes, connect edges, or modify your graph.',
          })}
        </p>
      </div>

      <div className="border-t border-[var(--border)] p-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t('graph.copilot.inputPlaceholder', { defaultValue: 'Type a message...' })}
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--skill-brand-600)]"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && input.trim()) {
                setInput('')
              }
            }}
          />
          <Button size="sm" disabled={!input.trim()} className="shrink-0">
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}

'use client'

import { ChevronDown, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

import { CopilotPanel } from './CopilotPanel'

interface CopilotOverlayProps {
  agentId: string
  expanded: boolean
  onToggle: () => void
}

export function CopilotOverlay({ agentId, expanded, onToggle }: CopilotOverlayProps) {
  const { t } = useTranslation()

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

      <div className="min-h-0 flex-1">
        <CopilotPanel />
      </div>
    </div>
  )
}

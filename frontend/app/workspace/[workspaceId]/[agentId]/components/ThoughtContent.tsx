'use client'

import { BrainCircuit } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { ExecutionStep } from '@/types'

interface ThoughtContentProps {
  step: ExecutionStep
  showHeader?: boolean
}

export function ThoughtContent({ step, showHeader = true }: ThoughtContentProps) {
  const isStreaming = step.status === 'running'
  const content = step.content || ''

  return (
    <div className="space-y-2">
      {showHeader && (
        <div className="flex items-center gap-2">
          <BrainCircuit size={14} className="text-purple-500" />
          <span className="text-[11px] font-semibold text-purple-600">{step.title}</span>
          {isStreaming && (
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-purple-500" />
              <span className="text-[9px] font-medium text-purple-500">Thinking...</span>
            </div>
          )}
        </div>
      )}

      <div className="prose prose-sm max-w-none">
        <div
          className={cn(
            'whitespace-pre-wrap font-mono text-xs leading-7 text-[var(--text-secondary)]',
            'rounded-lg border border-purple-100 bg-purple-50/50 p-3',
          )}
        >
          {content || <span className="italic text-[var(--text-muted)]">Thinking...</span>}
          {isStreaming && (
            <span className="ml-1 inline-block h-4 w-2 animate-pulse bg-purple-500 align-middle" />
          )}
        </div>
      </div>
    </div>
  )
}

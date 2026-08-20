'use client'

import { CheckCircle2, CircleStop, Loader2, RefreshCw, TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { QuickstartGenerationState } from '@/hooks/managed/use-quickstart-chat'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

interface QuickstartGenerationStatusProps {
  state: QuickstartGenerationState
  onCancel: () => void
  onRetry: () => void
}

export function QuickstartGenerationStatus({
  state,
  onCancel,
  onRetry,
}: QuickstartGenerationStatusProps) {
  const { t } = useTranslation()
  if (state.status === 'idle') return null

  const isGenerating = state.status === 'generating'
  const titleKey = isGenerating
    ? `managed.quickstart.generation.phase.${state.phase}`
    : `managed.quickstart.generation.status.${state.status}`

  const StatusIcon = isGenerating
    ? Loader2
    : state.status === 'complete'
      ? CheckCircle2
      : state.status === 'error'
        ? TriangleAlert
        : CircleStop

  return (
    <div
      className={cn(
        'border-b border-border px-4 py-3',
        state.status === 'error' && 'bg-destructive/5',
        state.status === 'cancelled' && 'bg-muted/40',
      )}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <StatusIcon
              className={cn(
                'h-4 w-4 shrink-0',
                isGenerating && 'animate-spin text-primary',
                state.status === 'complete' && 'text-emerald-600',
                state.status === 'error' && 'text-destructive',
                state.status === 'cancelled' && 'text-muted-foreground',
              )}
            />
            <span className="truncate">{t(titleKey)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {state.elapsedSeconds >= 5 ? (
              <span>
                {t('managed.quickstart.generation.elapsed', {
                  seconds: state.elapsedSeconds,
                })}
              </span>
            ) : null}
            {state.hasPartialConfig ? (
              <span className="text-emerald-700 dark:text-emerald-400">
                {t('managed.quickstart.generation.partialSaved')}
              </span>
            ) : null}
            {state.errorMessage ? <span>{state.errorMessage}</span> : null}
          </div>
        </div>
        {isGenerating ? (
          <Button variant="outline" size="sm" className="shrink-0 gap-1.5" onClick={onCancel}>
            <CircleStop className="h-3.5 w-3.5" />
            {t('managed.quickstart.generation.cancel')}
          </Button>
        ) : state.status === 'cancelled' || state.status === 'error' ? (
          <Button variant="outline" size="sm" className="shrink-0 gap-1.5" onClick={onRetry}>
            <RefreshCw className="h-3.5 w-3.5" />
            {t('managed.quickstart.generation.retry')}
          </Button>
        ) : null}
      </div>
    </div>
  )
}

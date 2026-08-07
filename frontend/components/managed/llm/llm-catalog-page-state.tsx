'use client'

import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

interface LlmCatalogPageStateProps {
  state: 'loading' | 'error'
  onRetry?: () => void
}

export function LlmCatalogPageState({ state, onRetry }: LlmCatalogPageStateProps) {
  const { t } = useTranslation()

  if (state === 'loading') {
    return (
      <div
        className="flex min-h-[360px] items-center justify-center gap-2 px-6 py-16 text-sm text-muted-foreground"
        aria-live="polite"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('managed.llm.loadingCatalog')}
      </div>
    )
  }

  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 rounded-full border border-border bg-destructive/5 p-4">
        <AlertTriangle className="h-10 w-10 text-destructive" />
      </div>
      <p className="mb-6 max-w-md text-sm leading-6 text-muted-foreground">
        {t('managed.llm.catalogLoadFailed')}
      </p>
      {onRetry ? (
        <Button onClick={onRetry}>
          <RefreshCw className="mr-1 h-4 w-4" />
          {t('common.retry')}
        </Button>
      ) : null}
    </div>
  )
}

'use client'

import { AlertTriangle, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { QuickstartRecommendationStatus } from '@/hooks/managed/use-quickstart-recommendation'
import { useTranslation } from '@/lib/i18n'

export function QuickstartRecommendationStatusCard({
  status,
  onRetry,
}: {
  status: QuickstartRecommendationStatus
  onRetry: () => void
}) {
  const { t } = useTranslation()

  if (status === 'idle' || status === 'ready') return null

  if (status === 'loading') {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-dashed border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t('managed.quickstart.recommendation.loading')}
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/5 p-3">
      <div className="flex items-start gap-2 text-xs text-destructive">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{t('managed.quickstart.recommendation.failed')}</span>
      </div>
      <Button type="button" size="sm" variant="outline" onClick={onRetry}>
        {t('common.retry')}
      </Button>
    </div>
  )
}

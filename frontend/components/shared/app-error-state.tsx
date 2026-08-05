'use client'

import { AlertTriangle, RefreshCw } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import { Button } from '@/components/ui/button'

interface AppErrorStateProps {
  title?: string
  description?: string
  onRetry?: () => void
  retryLabel?: string
}

export function AppErrorState({ title, description, onRetry, retryLabel }: AppErrorStateProps) {
  const { t } = useTranslation()

  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 rounded-full border border-border bg-muted/40 p-4">
        <AlertTriangle className="h-10 w-10 text-destructive" />
      </div>
      <h2 className="mb-2 text-lg font-semibold text-foreground">
        {title || t('common.pageErrorTitle')}
      </h2>
      <p className="mb-6 max-w-md text-sm leading-6 text-muted-foreground">
        {description || t('common.pageErrorDescription')}
      </p>
      {onRetry && (
        <Button onClick={onRetry}>
          <RefreshCw className="mr-1 h-4 w-4" />
          {retryLabel || t('common.retry')}
        </Button>
      )}
    </div>
  )
}

export function AppErrorStateView({ title, description, onRetry, retryLabel }: AppErrorStateProps) {
  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 rounded-full border border-border bg-muted/40 p-4">
        <AlertTriangle className="h-10 w-10 text-destructive" />
      </div>
      <h2 className="mb-2 text-lg font-semibold text-foreground">{title}</h2>
      <p className="mb-6 max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
      {onRetry && (
        <Button onClick={onRetry}>
          <RefreshCw className="mr-1 h-4 w-4" />
          {retryLabel}
        </Button>
      )}
    </div>
  )
}

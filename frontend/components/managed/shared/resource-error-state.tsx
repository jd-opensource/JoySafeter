'use client'

import { AlertTriangle, ArrowLeft, FileQuestion, RefreshCw, ShieldAlert } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import { Button } from '@/components/ui/button'

type ManagedResourceKind =
  | 'agent'
  | 'apiKey'
  | 'environment'
  | 'file'
  | 'memoryStore'
  | 'project'
  | 'secret'
  | 'session'
  | 'skill'
  | 'vault'

type ErrorReason = 'forbidden' | 'notFound' | 'unknown'

interface ResourceErrorStateProps {
  error?: unknown
  resource: ManagedResourceKind
  backLabel?: string
  onBack?: () => void
  onRetry?: () => void
}

function getErrorStatus(error: unknown): number | undefined {
  const apiError = error as { status?: number; response?: { status?: number } }
  return apiError?.status ?? apiError?.response?.status
}

function getErrorCode(error: unknown): string {
  const apiError = error as { code?: string; payload?: { code?: string } }
  return apiError?.code ?? apiError?.payload?.code ?? ''
}

function getErrorReason(error: unknown): ErrorReason {
  const status = getErrorStatus(error)
  const code = getErrorCode(error).toUpperCase()

  if (status === 403 || code.includes('FORBIDDEN') || code.includes('ACCESS_DENIED') || code.includes('WRITE_REQUIRED')) {
    return 'forbidden'
  }
  if (status === 404 || code.includes('NOT_FOUND')) {
    return 'notFound'
  }
  return 'unknown'
}

export function ResourceErrorState({
  error,
  resource,
  backLabel,
  onBack,
  onRetry,
}: ResourceErrorStateProps) {
  const { t } = useTranslation()
  const reason = getErrorReason(error)
  const Icon = reason === 'forbidden' ? ShieldAlert : reason === 'notFound' ? FileQuestion : AlertTriangle
  const iconClassName = reason === 'forbidden' || reason === 'unknown' ? 'text-destructive' : 'text-muted-foreground'

  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-4 rounded-full border border-border bg-muted/40 p-4">
        <Icon className={`h-10 w-10 ${iconClassName}`} />
      </div>
      <h2 className="mb-2 text-lg font-semibold text-foreground">
        {t(`managed.errorStates.${resource}.${reason}.title`)}
      </h2>
      <p className="mb-6 max-w-md text-sm leading-6 text-muted-foreground">
        {t(`managed.errorStates.${resource}.${reason}.description`)}
      </p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        {onBack && (
          <Button variant="outline" onClick={onBack}>
            <ArrowLeft className="mr-1 h-4 w-4" />
            {backLabel || t('common.back')}
          </Button>
        )}
        {onRetry && reason === 'unknown' && (
          <Button onClick={onRetry}>
            <RefreshCw className="mr-1 h-4 w-4" />
            {t('common.retry')}
          </Button>
        )}
      </div>
    </div>
  )
}

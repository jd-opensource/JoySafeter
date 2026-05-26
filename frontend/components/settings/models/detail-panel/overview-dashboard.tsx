'use client'

import { AlertTriangle, CheckCircle, HelpCircle, XCircle } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { useModelsOverview } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

export function OverviewDashboard() {
  const { t } = useTranslation()
  const { data: overview, isLoading } = useModelsOverview()

  if (isLoading || !overview) {
    return (
      <div className="space-y-6 p-6">
        <div className="grid grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4"
            >
              <Skeleton className="mb-2 h-4 w-16" />
              <Skeleton className="h-8 w-10" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4"
            >
              <Skeleton className="mb-2 h-3 w-16" />
              <Skeleton className="h-8 w-10" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-[var(--text-secondary)]">
          {t('settings.providerHealth')}
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4">
            <div className="mb-1 flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-[var(--status-success)]" />
              <span className="text-xs text-[var(--text-tertiary)]">{t('settings.healthy')}</span>
            </div>
            <p className="text-2xl font-bold text-[var(--text-primary)]">
              {overview.healthy_providers}
            </p>
          </div>
          <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4">
            <div className="mb-1 flex items-center gap-2">
              <XCircle className="h-4 w-4 text-[var(--status-error)]" />
              <span className="text-xs text-[var(--text-tertiary)]">{t('settings.unhealthy')}</span>
            </div>
            <p className="text-2xl font-bold text-[var(--text-primary)]">
              {overview.unhealthy_providers}
            </p>
          </div>
          <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4">
            <div className="mb-1 flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-[var(--text-muted)]" />
              <span className="text-xs text-[var(--text-tertiary)]">
                {t('settings.notConfiguredStatus')}
              </span>
            </div>
            <p className="text-2xl font-bold text-[var(--text-primary)]">
              {overview.unconfigured_providers}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4">
          <p className="mb-1 text-xs text-[var(--text-tertiary)]">{t('settings.totalModels')}</p>
          <p className="text-2xl font-bold text-[var(--text-primary)]">{overview.total_models}</p>
        </div>
        <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4">
          <p className="mb-1 text-xs text-[var(--text-tertiary)]">
            {t('settings.availableModels')}
          </p>
          <p className="text-2xl font-bold text-[var(--status-success)]">
            {overview.available_models}
          </p>
        </div>
      </div>

      {overview.recent_credential_failure && (
        <div className="rounded-lg border border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-warning)]" />
            <div>
              <p className="mb-1 text-xs font-semibold text-[var(--status-warning-strong,var(--status-warning))]">
                {t('settings.recentCredentialFailure', {
                  provider: overview.recent_credential_failure.provider_display_name,
                })}
              </p>
              <p className="line-clamp-2 text-xs text-[var(--status-warning)]">
                {overview.recent_credential_failure.error}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

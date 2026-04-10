'use client'

import { AlertCircle, Wifi, WifiOff, Loader2, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

import { useBuilderStore } from '../stores/builderStore'

export function GraphStatusBar() {
  const { t } = useTranslation()
  const {
    lastAutoSaveTime,
    deployedAt,
    hasPendingChanges,
    lastSaveError,
    saveRetryCount,
    isSaving,
    graphId,
    autoSave,
  } = useBuilderStore()

  const formatTime = (timestamp: number | null): string => {
    if (!timestamp) return ''
    const date = new Date(timestamp)
    const hours = date.getHours().toString().padStart(2, '0')
    const minutes = date.getMinutes().toString().padStart(2, '0')
    const seconds = date.getSeconds().toString().padStart(2, '0')
    return `${hours}:${minutes}:${seconds}`
  }

  const formatPublishedTime = (publishedAt: string | null): string => {
    if (!publishedAt) return ''
    const published = new Date(publishedAt)
    const now = new Date()
    const diffMs = now.getTime() - published.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) {
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
      if (diffHours === 0) {
        const diffMinutes = Math.floor(diffMs / (1000 * 60))
        return diffMinutes <= 0
          ? t('workspace.justPublished')
          : t('workspace.publishedMinutesAgo', { minutes: diffMinutes })
      }
      return t('workspace.publishedHoursAgo', { hours: diffHours })
    }
    return t('workspace.publishedDaysAgo', { days: diffDays })
  }

  // Render save status
  const renderSaveStatus = () => {
    // Check if graph is ready for saving
    const isGraphReady = graphId !== null

    // Network offline status
    if (lastSaveError === 'offline') {
      return (
        <span className="flex items-center gap-1 text-[var(--status-warning)]">
          <WifiOff size={12} />
          {t('workspace.offline')}
        </span>
      )
    }

    // Currently saving
    if (isSaving) {
      return (
        <span className="flex items-center gap-1 text-primary">
          <Loader2 size={12} className="animate-spin" />
          {t('workspace.saving')}
        </span>
      )
    }

    // Save failed with unsaved changes
    if (lastSaveError && hasPendingChanges && saveRetryCount >= 3) {
      return (
        <span className="flex items-center gap-1 text-[var(--status-error)]" title={lastSaveError}>
          <AlertCircle size={12} />
          {t('workspace.saveFailedStatus')}
        </span>
      )
    }

    // Retrying
    if (saveRetryCount > 0 && saveRetryCount < 3) {
      return (
        <span className="text-[var(--status-warning)]">
          {t('workspace.retrying')} ({saveRetryCount}/3)
        </span>
      )
    }

    // Graph not ready for saving
    if (!isGraphReady) {
      return (
        <span className="text-[var(--text-muted)]" title={t('workspace.waiting')}>
          {t('workspace.waiting')}
        </span>
      )
    }

    // Has unsaved changes
    if (hasPendingChanges) {
      return (
        <span className="flex items-center gap-1.5 text-[var(--text-muted)]">
          {t('workspace.unsavedChanges')}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => autoSave()}
            className="h-5 px-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]"
          >
            <Save size={11} className="mr-1" />
            {t('workspace.save')}
          </Button>
        </span>
      )
    }

    // Normally display last save time
    if (lastAutoSaveTime) {
      return (
        <span className="flex items-center gap-1">
          <Wifi size={12} className="text-[var(--status-success)]" />
          {t('workspace.autoSaved')} {formatTime(lastAutoSaveTime)}
        </span>
      )
    }

    return <span className="text-[var(--text-muted)]">{t('workspace.autoSaved')} --:--:--</span>
  }

  return (
    <div className="text-xs text-[var(--text-secondary)]">
      <div className="flex items-center gap-2">
        {renderSaveStatus()}
        <span className="text-[var(--text-subtle)]">·</span>
        {deployedAt ? (
          <span>{formatPublishedTime(deployedAt)}</span>
        ) : (
          <span className="text-[var(--text-muted)]">{t('workspace.unpublished')}</span>
        )}
      </div>
    </div>
  )
}

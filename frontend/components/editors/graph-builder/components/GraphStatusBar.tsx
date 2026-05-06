'use client'

import { AlertCircle, Wifi, WifiOff, Loader2, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

import { useGraphStore } from '../stores/graphStore'
import { useSaveStore } from '../stores/saveStore'
import { ZoomControls } from './ZoomControls'

export function GraphStatusBar() {
  const { t } = useTranslation()
  const { lastAutoSaveTime, hasPendingChanges, lastSaveError, saveRetryCount, isSaving, autoSave } =
    useSaveStore()
  const graphId = useGraphStore((s) => s.graphId)

  const formatTime = (timestamp: number | null): string => {
    if (!timestamp) return ''
    const date = new Date(timestamp)
    const hours = date.getHours().toString().padStart(2, '0')
    const minutes = date.getMinutes().toString().padStart(2, '0')
    const seconds = date.getSeconds().toString().padStart(2, '0')
    return `${hours}:${minutes}:${seconds}`
  }

  const renderSaveStatus = () => {
    const isGraphReady = graphId !== null

    if (lastSaveError === 'offline') {
      return (
        <span className="flex items-center gap-1 text-[var(--status-warning)]">
          <WifiOff size={12} />
          {t('workspace.offline')}
        </span>
      )
    }

    if (isSaving) {
      return (
        <span className="flex items-center gap-1 text-primary">
          <Loader2 size={12} className="animate-spin" />
          {t('workspace.saving')}
        </span>
      )
    }

    if (lastSaveError && hasPendingChanges && saveRetryCount >= 3) {
      return (
        <span className="flex items-center gap-1 text-[var(--status-error)]" title={lastSaveError}>
          <AlertCircle size={12} />
          {t('workspace.saveFailedStatus')}
        </span>
      )
    }

    if (saveRetryCount > 0 && saveRetryCount < 3) {
      return (
        <span className="text-[var(--status-warning)]">
          {t('workspace.retrying')} ({saveRetryCount}/3)
        </span>
      )
    }

    if (!isGraphReady) {
      return (
        <span className="text-[var(--text-muted)]" title={t('workspace.waiting')}>
          {t('workspace.waiting')}
        </span>
      )
    }

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
    <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-1 text-xs text-[var(--text-secondary)]">
      <div className="flex items-center">{renderSaveStatus()}</div>
      <ZoomControls />
    </div>
  )
}

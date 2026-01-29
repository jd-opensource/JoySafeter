'use client'

import { AlertCircle, Wifi, WifiOff, Loader2 } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

import { useBuilderStore } from '../stores/builderStore'


export const GraphStatusBar: React.FC = () => {
  const { t } = useTranslation()
  const { lastAutoSaveTime, deployedAt, hasPendingChanges, lastSaveError, saveRetryCount, isSaving, graphId, graphName } = useBuilderStore()

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
        <span className="text-amber-600 flex items-center gap-1">
          <WifiOff size={12} />
          {t('status.offline', { defaultValue: '离线' })}
        </span>
      )
    }

    // Currently saving
    if (isSaving) {
      return (
        <span className="text-blue-500 flex items-center gap-1">
          <Loader2 size={12} className="animate-spin" />
          {t('status.saving', { defaultValue: '保存中...' })}
        </span>
      )
    }

    // Save failed with unsaved changes
    if (lastSaveError && hasPendingChanges && saveRetryCount >= 3) {
      return (
        <span className="text-red-500 flex items-center gap-1" title={lastSaveError}>
          <AlertCircle size={12} />
          {t('status.saveFailed', { defaultValue: '保存失败' })}
        </span>
      )
    }

    // Retrying
    if (saveRetryCount > 0 && saveRetryCount < 3) {
      return (
        <span className="text-amber-500">
          {t('status.retrying', { defaultValue: '重试中' })} ({saveRetryCount}/3)
        </span>
      )
    }

    // Graph not ready for saving
    if (!isGraphReady) {
      return (
        <span className="text-gray-400" title="等待图表初始化...">
          {t('status.waiting', { defaultValue: '等待中...' })}
        </span>
      )
    }

    // Has unsaved changes
    if (hasPendingChanges) {
      return (
        <span className="text-gray-400">
          {t('status.unsavedChanges', { defaultValue: '有未保存的更改' })}
        </span>
      )
    }
    
    // Normally display last save time
    if (lastAutoSaveTime) {
      return (
        <span className="flex items-center gap-1">
          <Wifi size={12} className="text-green-500" />
          {t('workspace.autoSaved')} {formatTime(lastAutoSaveTime)}
        </span>
      )
    }
    
    return (
      <span className="text-gray-400">{t('workspace.autoSaved')} --:--:--</span>
    )
  }

  return (
    <div className="text-xs text-gray-700">
      <div className="flex items-center gap-2">
        {renderSaveStatus()}
        <span className="text-gray-300">·</span>
        {deployedAt ? (
          <span>
            {formatPublishedTime(deployedAt)}
          </span>
        ) : (
          <span className="text-gray-400">{t('workspace.unpublished')}</span>
        )}
      </div>
    </div>
  )
}


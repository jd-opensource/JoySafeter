'use client'

import React from 'react'
import { Loader2, Eye } from 'lucide-react'

import { Button } from '@/components/ui/button'

import { GraphPreview } from './GraphPreview'

import type { GraphVersionState } from '@/services/graphDeploymentService'

interface DeploymentPreviewProps {
  previewMode: 'current' | 'selected'
  selectedVersion: number | null
  selectedVersionName: string | undefined
  showToggle: boolean
  isLoadingPreview: boolean
  previewState: GraphVersionState
  onSetPreviewMode: (mode: 'current' | 'selected') => void
  t: (key: string, options?: Record<string, unknown>) => string
}

export const DeploymentPreview = React.memo(function DeploymentPreview({
  previewMode,
  selectedVersion,
  selectedVersionName,
  showToggle,
  isLoadingPreview,
  previewState,
  onSetPreviewMode,
  t,
}: DeploymentPreviewProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text-secondary)]">
          {previewMode === 'selected' && selectedVersionName
            ? selectedVersionName
            : t('workspace.currentDraft')}
        </span>
        {showToggle && (
          <div className="flex gap-1">
            <Button
              size="sm"
              variant={previewMode === 'current' ? 'default' : 'ghost'}
              className="h-6 px-2 text-xs"
              onClick={() => onSetPreviewMode('current')}
            >
              {t('workspace.current')}
            </Button>
            <Button
              size="sm"
              variant={previewMode === 'selected' ? 'default' : 'ghost'}
              className="h-6 px-2 text-xs"
              onClick={() => onSetPreviewMode('selected')}
            >
              v{selectedVersion}
            </Button>
          </div>
        )}
      </div>

      <div className="relative">
        {isLoadingPreview && previewMode === 'selected' && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-[var(--surface-elevated)]">
            <Loader2 size={24} className="animate-spin text-[var(--text-muted)]" />
          </div>
        )}
        <GraphPreview state={previewState} height={300} className="bg-[var(--surface-2)]" />
      </div>
    </div>
  )
})

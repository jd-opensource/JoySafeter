'use client'

import { FolderOpen, X } from 'lucide-react'
import React, { useCallback, useEffect, useMemo, useState } from 'react'

import ArtifactPanel from '@/app/chat/components/ArtifactPanel'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { artifactService, type RunInfo } from '@/services/artifactService'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface ArtifactsDrawerProps {
  isOpen: boolean
  onClose: () => void
  threadId: string
  runId: string
}

const ArtifactsDrawer: React.FC<ArtifactsDrawerProps> = ({ isOpen, onClose, threadId, runId }) => {
  const { t } = useTranslation()

  const [runs, setRuns] = useState<RunInfo[]>([])
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runId ?? null)

  useEffect(() => {
    setSelectedRunId(runId ?? null)
  }, [runId])

  const loadRuns = useCallback(async () => {
    if (!threadId) return
    setLoadingRuns(true)
    setError(null)
    try {
      const list = await artifactService.listRuns(threadId)
      setRuns(list)
      if (list.length && !selectedRunId) setSelectedRunId(list[0].run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load runs')
    } finally {
      setLoadingRuns(false)
    }
  }, [threadId])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  const runLabel = useMemo(() => {
    const r = runs.find((x) => x.run_id === selectedRunId)
    if (!r || !selectedRunId) return ''
    return `${selectedRunId.slice(0, 8)}… (${r.file_count} files)`
  }, [runs, selectedRunId])

  if (!isOpen) return null

  return (
    <div
      className={cn(
        'h-full overflow-hidden',
        'bg-white flex flex-col'
      )}
    >
      <div className="px-4 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white shrink-0">
        <div className="flex items-center gap-3 text-gray-900 overflow-hidden min-w-0">
          <div className="p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0 bg-blue-50 text-blue-600">
            <FolderOpen size={14} />
          </div>
          <h3 className="font-bold text-sm leading-tight truncate">
            {t('chat.artifacts', { defaultValue: 'Artifacts' })}
          </h3>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Select
            value={selectedRunId ?? ''}
            onValueChange={(v) => setSelectedRunId(v || null)}
            disabled={loadingRuns}
          >
            <SelectTrigger className="h-8 w-[180px] text-xs bg-white border-gray-200 focus:ring-1">
              <SelectValue
                placeholder={loadingRuns ? 'Loading…' : runs.length ? 'Select run…' : 'No runs'}
              >
                <span className="truncate">{runLabel}</span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="max-h-[260px]">
              {runs.map((r) => (
                <SelectItem key={r.run_id} value={r.run_id} className="text-xs">
                  {r.run_id.slice(0, 8)}… ({r.file_count} files)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-7 w-7 text-gray-300 hover:text-gray-600 hover:bg-gray-100"
            aria-label={t('chat.closeArtifacts', { defaultValue: 'Close artifacts' })}
          >
            <X size={16} />
          </Button>
        </div>
      </div>

      {error && <div className="px-4 py-2 text-xs text-red-600 border-b border-gray-100">{error}</div>}

      <ArtifactPanel threadId={threadId} runId={selectedRunId} className="flex-1 min-h-0" />
    </div>
  )
}

export default ArtifactsDrawer


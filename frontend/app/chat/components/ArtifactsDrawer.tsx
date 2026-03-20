'use client'

import { FolderOpen, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import ArtifactPanel, { type LiveFileEntry } from '@/app/chat/components/ArtifactPanel'
import { cn } from '@/lib/utils'
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
  liveFiles?: LiveFileEntry[]
}

export default function ArtifactsDrawer({
  isOpen,
  onClose,
  threadId,
  runId,
  liveFiles,
}: ArtifactsDrawerProps) {
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
    <div className={cn('h-full overflow-hidden', 'flex flex-col bg-white')}>
      <div className="flex shrink-0 items-center justify-between border-b border-gray-100 bg-white px-4 py-3.5">
        <div className="flex min-w-0 items-center gap-3 overflow-hidden text-gray-900">
          <div className="shrink-0 rounded-lg border border-gray-50 bg-blue-50 p-1.5 text-blue-600 shadow-sm">
            <FolderOpen size={14} />
          </div>
          <h3 className="truncate text-sm font-bold leading-tight">
            {t('chat.artifacts', { defaultValue: 'Artifacts' })}
          </h3>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Select
            value={selectedRunId ?? ''}
            onValueChange={(v) => setSelectedRunId(v || null)}
            disabled={loadingRuns}
          >
            <SelectTrigger className="h-8 w-[180px] border-gray-200 bg-white text-xs focus:ring-1">
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
            className="h-7 w-7 text-gray-300 hover:bg-gray-100 hover:text-gray-600"
            aria-label={t('chat.closeArtifacts', { defaultValue: 'Close artifacts' })}
          >
            <X size={16} />
          </Button>
        </div>
      </div>

      {error && (
        <div className="border-b border-gray-100 px-4 py-2 text-xs text-red-600">{error}</div>
      )}

      <ArtifactPanel threadId={threadId} runId={selectedRunId} liveFiles={liveFiles} className="min-h-0 flex-1" />
    </div>
  )
}

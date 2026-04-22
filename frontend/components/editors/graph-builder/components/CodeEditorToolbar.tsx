'use client'

import { Loader2, Play, Save } from 'lucide-react'
import { useState, useRef } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { apiPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { getErrorMessage } from '@/lib/utils/toast'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorToolbar({ graphId, workspaceId }: Props) {
  const { t } = useTranslation()
  const isDirty = useCodeEditorStore((s) => s.isDirty)
  const isSaving = useCodeEditorStore((s) => s.isSaving)
  const save = useCodeEditorStore((s) => s.save)
  const graphName = useCodeEditorStore((s) => s.graphName)
  const setGraphName = useCodeEditorStore((s) => s.setGraphName)

  const [isRunning, setIsRunning] = useState(false)
  const [runResult, setRunResult] = useState<any>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [runDuration, setRunDuration] = useState<number | null>(null)
  const startTimeRef = useRef<number>(0)

  const handleRun = async () => {
    if (isDirty) {
      await save()
    }
    setIsRunning(true)
    setRunResult(null)
    setRunError(null)
    setRunDuration(null)
    startTimeRef.current = Date.now()
    try {
      const result = await apiPost<any>(`graphs/${graphId}/code/run`, { input: {} })
      setRunResult(result?.result ?? result)
    } catch (e: unknown) {
      setRunError(getErrorMessage(e, t('common.operationFailed')))
    } finally {
      setRunDuration(Date.now() - startTimeRef.current)
      setIsRunning(false)
    }
  }

  return (
    <div className="flex shrink-0 flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2">
        {/* Left: graph name */}
        <input
          className="min-w-0 max-w-xs flex-1 border-none bg-transparent text-sm font-medium text-[var(--text-primary)] outline-none"
          value={graphName ?? ''}
          onChange={(e) => setGraphName(e.target.value)}
          placeholder={t('workspace.untitledGraph')}
        />

        {/* Right: actions */}
        <div className="flex items-center gap-2">
          <button
            className="flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)] disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => save()}
            disabled={!isDirty || isSaving}
          >
            {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            {isSaving ? t('workspace.savingEllipsis') : t('workspace.save')}
          </button>

          <button
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-white transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              isRunning ? 'bg-[var(--status-warning)]' : 'bg-primary hover:bg-primary/90'
            }`}
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {isRunning ? t('workspace.runningEllipsis') : t('workspace.runButton')}
          </button>
        </div>
      </div>

      {/* Run result / error panel */}
      {(runResult || runError) && (
        <div
          className={`border-b border-[var(--border)] px-4 py-3 text-sm ${
            runError
              ? 'bg-[var(--status-error-bg)] text-[var(--status-error)]'
              : 'bg-[var(--status-success-bg)] text-[var(--status-success)]'
          }`}
        >
          <div className="mb-1.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium">
                {runError ? t('workspace.error') : t('workspace.result')}
              </span>
              {runDuration !== null && (
                <span className="text-xs opacity-60">{(runDuration / 1000).toFixed(1)}s</span>
              )}
            </div>
            <button
              className="text-xs opacity-50 transition-opacity hover:opacity-100"
              onClick={() => {
                setRunResult(null)
                setRunError(null)
                setRunDuration(null)
              }}
            >
              {t('workspace.close')}
            </button>
          </div>
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap font-mono text-sm leading-relaxed">
            {runError || JSON.stringify(runResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

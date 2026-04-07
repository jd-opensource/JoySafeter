'use client'

import { Loader2, Play, Save } from 'lucide-react'
import { useState, useRef } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { apiPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'

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
      setRunError(e instanceof Error ? e.message : t('common.operationFailed'))
    } finally {
      setRunDuration(Date.now() - startTimeRef.current)
      setIsRunning(false)
    }
  }

  return (
    <div className="flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border)] bg-[var(--surface-1)]">
        {/* Left: graph name */}
        <input
          className="text-sm font-medium bg-transparent border-none outline-none min-w-0 flex-1 max-w-xs text-[var(--text-primary)]"
          value={graphName ?? ''}
          onChange={(e) => setGraphName(e.target.value)}
          placeholder={t('workspace.untitledGraph')}
        />

        {/* Right: actions */}
        <div className="flex items-center gap-2">
          <button
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[var(--border)] rounded-md hover:bg-[var(--surface-2)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            onClick={() => save()}
            disabled={!isDirty || isSaving}
          >
            {isSaving ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Save size={13} />
            )}
            {isSaving ? t('workspace.savingEllipsis') : t('workspace.save')}
          </button>

          <button
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              isRunning
                ? 'bg-amber-600'
                : 'bg-primary hover:bg-primary/90'
            }`}
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Play size={13} />
            )}
            {isRunning ? t('workspace.runningEllipsis') : t('workspace.runButton')}
          </button>
        </div>
      </div>

      {/* Run result / error panel */}
      {(runResult || runError) && (
        <div className={`border-b border-[var(--border)] px-4 py-3 text-sm ${
          runError
            ? 'bg-red-500/5 text-red-700 dark:text-red-400'
            : 'bg-green-500/5 text-green-700 dark:text-green-400'
        }`}>
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-2">
              <span className="font-medium text-xs">{runError ? t('workspace.error') : t('workspace.result')}</span>
              {runDuration !== null && (
                <span className="text-2xs opacity-60">
                  {(runDuration / 1000).toFixed(1)}s
                </span>
              )}
            </div>
            <button
              className="text-2xs opacity-50 hover:opacity-100 transition-opacity"
              onClick={() => { setRunResult(null); setRunError(null); setRunDuration(null) }}
            >
              {t('workspace.close')}
            </button>
          </div>
          <pre className="whitespace-pre-wrap font-mono text-app-xs max-h-60 overflow-auto leading-relaxed">
            {runError || JSON.stringify(runResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

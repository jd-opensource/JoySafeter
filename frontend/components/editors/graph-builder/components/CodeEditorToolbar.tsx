'use client'

import { Loader2, Play, Save, Square } from 'lucide-react'
import { useCallback, useState } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { useTranslation } from '@/lib/i18n'
import { useAgent } from '@/hooks/queries/agents'
import { agentRunService } from '@/services/agentRunService'
import { useExecutionStream } from '@/hooks/use-execution-stream'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/agent-run'

interface Props {
  graphId: string
  workspaceId: string
}

interface ActiveRun {
  runId: string
  executionId: string
}

export function CodeEditorToolbar({ graphId, workspaceId }: Props) {
  const { t } = useTranslation()
  const isDirty = useCodeEditorStore((s) => s.isDirty)
  const isSaving = useCodeEditorStore((s) => s.isSaving)
  const save = useCodeEditorStore((s) => s.save)
  const graphName = useCodeEditorStore((s) => s.graphName)
  const setGraphName = useCodeEditorStore((s) => s.setGraphName)

  const [runError, setRunError] = useState<string | null>(null)
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null)

  const { data: agent } = useAgent(graphId, workspaceId)

  const { status: wsStatus } = useExecutionStream({
    executionId: activeRun?.executionId || '',
    enabled: Boolean(activeRun),
  })

  const isExecuting = Boolean(
    activeRun &&
    wsStatus &&
    !TERMINAL_EXECUTION_STATUSES.includes(wsStatus as never),
  )

  const handleRun = useCallback(async () => {
    setRunError(null)

    if (isDirty) {
      await save()
    }

    if (!agent?.active_release_id) {
      setRunError(t('workspace.codeRunNoRelease'))
      return
    }

    try {
      const run = await agentRunService.create({
        release_id: agent.active_release_id,
        trigger_source: 'api',
        goal: 'Code mode run',
      })
      if (run.current_execution_id) {
        setActiveRun({ runId: run.id, executionId: run.current_execution_id })
      }
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err))
    }
  }, [isDirty, save, agent, t])

  const handleCancel = useCallback(async () => {
    if (!activeRun) return
    try {
      await agentRunService.cancel(activeRun.runId)
    } catch {
      // Best-effort cancel
    }
    setActiveRun(null)
  }, [activeRun])

  return (
    <div className="flex shrink-0 flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2">
        <input
          className="min-w-0 max-w-xs flex-1 border-none bg-transparent text-sm font-medium text-[var(--text-primary)] outline-none"
          value={graphName ?? ''}
          onChange={(e) => setGraphName(e.target.value)}
          placeholder={t('workspace.untitledGraph')}
        />

        <div className="flex items-center gap-2">
          <button
            className="flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)] disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => save()}
            disabled={!isDirty || isSaving}
          >
            {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            {isSaving ? t('workspace.savingEllipsis') : t('workspace.save')}
          </button>

          {isExecuting ? (
            <button
              className="flex items-center gap-1.5 rounded-md bg-[var(--status-error)] px-3 py-1.5 text-xs text-white transition-colors hover:bg-[var(--status-error)]/90"
              onClick={handleCancel}
            >
              <Square size={13} />
              {t('workspace.stopButton')}
            </button>
          ) : (
            <button
              className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs text-white transition-colors hover:bg-primary/90"
              onClick={handleRun}
            >
              <Play size={13} />
              {t('workspace.runButton')}
            </button>
          )}
        </div>
      </div>

      {runError && (
        <div className="border-b border-[var(--border)] bg-[var(--status-error-bg)] px-4 py-3 text-sm text-[var(--status-error)]">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-medium">{t('workspace.error')}</span>
            <button
              className="text-xs opacity-50 transition-opacity hover:opacity-100"
              onClick={() => setRunError(null)}
            >
              {t('workspace.close')}
            </button>
          </div>
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap font-mono text-sm leading-relaxed">
            {runError}
          </pre>
        </div>
      )}
    </div>
  )
}

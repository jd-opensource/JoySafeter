'use client'

import { Loader2, Play, Save } from 'lucide-react'
import { useState } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
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

  const [runError, setRunError] = useState<string | null>(null)

  const handleRun = async () => {
    if (isDirty) {
      await save()
    }
    // TODO: 走 POST /v1/runs — 需后端注册 CodeEngine 处理 definition_kind="code"
    setRunError('Code run is not yet supported — waiting for backend CodeEngine registration')
  }

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

          <button
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs text-white transition-colors hover:bg-primary/90"
            onClick={handleRun}
          >
            <Play size={13} />
            {t('workspace.runButton')}
          </button>
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

'use client'

import { Loader2, Save } from 'lucide-react'
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

  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2">
      <input
        className="min-w-0 max-w-xs flex-1 border-none bg-transparent text-sm font-medium text-[var(--text-primary)] outline-none"
        value={graphName ?? ''}
        onChange={(e) => setGraphName(e.target.value)}
        placeholder={t('workspace.untitledGraph')}
      />

      <button
        className="flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)] disabled:cursor-not-allowed disabled:opacity-40"
        onClick={() => save()}
        disabled={!isDirty || isSaving}
      >
        {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
        {isSaving ? t('workspace.savingEllipsis') : t('workspace.save')}
      </button>
    </div>
  )
}

'use client'

import { Redo2, Undo2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/permissions-provider'
import { useGraphStore } from '../stores/graphStore'
import { AddNodeButton } from './AddNodeButton'
import { ImportExportMenu } from './ImportExportMenu'

export function GraphToolbar() {
  const { t } = useTranslation()
  const { canEdit } = useUserPermissionsContext()
  const addNode = useGraphStore((s) => s.addNode)
  const canUndo = useGraphStore((s) => s.past.length > 0)
  const canRedo = useGraphStore((s) => s.future.length > 0)
  const undo = useGraphStore((s) => s.undo)
  const redo = useGraphStore((s) => s.redo)

  const handleAddNode = (node: { type: string; label: string }) => {
    addNode(node.type, { x: 200, y: 200 }, node.label)
  }

  return (
    <div className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 shadow-md">
      {canEdit && <AddNodeButton onAddNode={handleAddNode} />}
      <ImportExportMenu />
      <div className="mx-1 h-4 w-px bg-[var(--border)]" />
      <Button
        variant="ghost"
        size="sm"
        className="h-7 w-7 p-0"
        disabled={!canUndo || !canEdit}
        onClick={undo}
        aria-label={t('workspace.undo', { defaultValue: 'Undo' })}
      >
        <Undo2 className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 w-7 p-0"
        disabled={!canRedo || !canEdit}
        onClick={redo}
        aria-label={t('workspace.redo', { defaultValue: 'Redo' })}
      >
        <Redo2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

'use client'

import { Beaker, Rocket } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import { useGraphStore } from '../stores/graphStore'
import { AddNodeButton } from './AddNodeButton'
import { ImportExportMenu } from './ImportExportMenu'

interface GraphToolbarProps {
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
  onImport?: (e: React.ChangeEvent<HTMLInputElement>) => void
  onExport?: () => void
}

export function GraphToolbar({ onOpenTestLab, onOpenRelease, onImport, onExport }: GraphToolbarProps) {
  const { t } = useTranslation()
  const { canEdit } = useUserPermissionsContext()
  const addNode = useGraphStore((s) => s.addNode)

  const handleAddNode = (node: { type: string; label: string }) => {
    // Place new nodes near the center; BuilderCanvas will handle viewport offset
    addNode(node.type, { x: 200, y: 200 }, node.label)
  }

  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1.5">
      <div className="flex items-center gap-1">
        {canEdit && <AddNodeButton onAddNode={handleAddNode} />}
        <ImportExportMenu onImport={onImport} onExport={onExport} />
      </div>
      <div className="flex items-center gap-1.5">
        {onOpenTestLab && (
          <Button variant="outline" size="sm" onClick={onOpenTestLab} className="h-7 gap-1.5 px-2.5 text-xs">
            <Beaker className="h-3.5 w-3.5" />
            {t('agents.build.test', { defaultValue: 'Test' })}
          </Button>
        )}
        {onOpenRelease && (
          <Button size="sm" onClick={onOpenRelease} className="h-7 gap-1.5 px-2.5 text-xs">
            <Rocket className="h-3.5 w-3.5" />
            {t('agents.build.release', { defaultValue: 'Release' })}
          </Button>
        )}
      </div>
    </div>
  )
}

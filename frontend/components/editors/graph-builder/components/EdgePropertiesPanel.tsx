'use client'

import { X, ArrowRight, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Node, Edge } from 'reactflow'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'

import { EdgeData } from '../types/graph'

interface EdgePropertiesPanelProps {
  edge: Edge
  nodes: Node[]
  edges: Edge[]
  onUpdate: (id: string, data: Partial<EdgeData>) => void
  onDelete?: (id: string) => void
  onClose: () => void
  embedded?: boolean
}

export function EdgePropertiesPanel({
  edge,
  nodes,
  edges: _edges,
  onUpdate,
  onDelete,
  onClose,
  embedded = false,
}: EdgePropertiesPanelProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const userPermissions = useUserPermissionsContext()

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const edgeData = useMemo(() => (edge.data || {}) as EdgeData, [edge.data])

  const sourceNode = nodes.find((n) => n.id === edge.source)
  const targetNode = nodes.find((n) => n.id === edge.target)
  const sourceLabel = (sourceNode?.data as any)?.label || edge.source.slice(0, 8)
  const targetLabel = (targetNode?.data as any)?.label || edge.target.slice(0, 8)

  const handleDelete = () => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditEdge', { defaultValue: 'Cannot edit edge' }),
        variant: 'destructive',
      })
      return
    }
    onDelete?.(edge.id)
    onClose()
  }

  return (
    <>
      <div
        className={
          embedded
            ? 'flex h-full flex-col overflow-hidden bg-[var(--surface-1)]'
            : 'absolute right-4 top-16 z-50 w-72 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-xl'
        }
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <div className="flex items-center gap-2">
            <ArrowRight size={14} className="text-[var(--text-muted)]" />
            <span className="text-sm font-medium">
              {t('workspace.edgeProperties', { defaultValue: 'Edge Properties' })}
            </span>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="h-6 w-6">
            <X size={14} />
          </Button>
        </div>

        {/* Body */}
        <div className="space-y-4 p-4">
          {/* Connection info */}
          <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
              {sourceLabel}
            </span>
            <ArrowRight size={12} />
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
              {targetLabel}
            </span>
          </div>

          {/* Label */}
          <div className="space-y-1.5">
            <Label className="text-xs">{t('workspace.edgeLabel', { defaultValue: 'Label' })}</Label>
            <Input
              value={edgeData.label || ''}
              onChange={(e) => onUpdate(edge.id, { ...edgeData, label: e.target.value })}
              placeholder="Optional label..."
              className="h-8 text-xs"
              disabled={!userPermissions.canEdit}
            />
          </div>

          {/* Delete */}
          {onDelete && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowDeleteConfirm(true)}
              disabled={!userPermissions.canEdit}
              className="w-full text-xs text-[var(--status-error)] hover:bg-[var(--status-error-bg)] hover:text-[var(--status-error-hover)]"
            >
              <Trash2 size={12} className="mr-1.5" />
              {t('workspace.deleteEdge', { defaultValue: 'Delete Edge' })}
            </Button>
          )}
        </div>
      </div>

      {/* Delete confirmation */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('workspace.deleteEdgeConfirmTitle', { defaultValue: 'Delete Edge?' })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('workspace.deleteEdgeConfirmMessage', {
                defaultValue: 'This will remove the connection between nodes.',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('workspace.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {t('workspace.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

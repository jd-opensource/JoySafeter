'use client'

import { AlertCircle, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

import { nodeRegistry } from '../services/nodeRegistry'
import { useGraphStore } from '../stores/graphStore'
import { EdgePropertiesPanel } from './EdgePropertiesPanel'
import PropertiesPanel from './PropertiesPanel'

interface InspectorPanelProps {
  onClose: () => void
}

export function InspectorPanel({ onClose }: InspectorPanelProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const userPermissions = useUserPermissionsContext()
  const {
    nodes,
    edges,
    selectedNodeId,
    selectedEdgeId,
    updateNodeConfig,
    updateNodeLabel,
    updateEdge,
    onEdgesChange,
    selectNode,
    selectEdge,
    takeSnapshot,
  } = useGraphStore()

  const selectedNode = nodes.find((n) => n.id === selectedNodeId)
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId)

  const nodeData = selectedNode?.data as
    | { type: string; label?: string; config?: Record<string, unknown> }
    | undefined
  const nodeDef = nodeData ? nodeRegistry.get(nodeData.type) : undefined

  const edgeTitle = selectedEdge
    ? t('agents.studio.rightPanel.edgeInspector', { defaultValue: 'Edge Inspector' })
    : ''

  const denyEdit = () =>
    toast({
      title: t('workspace.noPermission'),
      description: t('workspace.cannotEditNode'),
      variant: 'destructive',
    })

  const NodeIcon = nodeDef?.icon || AlertCircle

  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  useEffect(() => {
    setIsEditingName(false)
  }, [selectedNodeId])

  const startEditingName = () => {
    if (!userPermissions.canEdit) return
    setEditName(nodeData?.label || nodeDef?.label || '')
    setIsEditingName(true)
  }

  const commitName = () => {
    const trimmed = editName.trim()
    if (trimmed && selectedNodeId && trimmed !== (nodeData?.label || '')) {
      takeSnapshot()
      updateNodeLabel(selectedNodeId, trimmed)
    }
    setIsEditingName(false)
  }

  return (
    <div className="flex h-full flex-col bg-[var(--surface-1)]">
      {selectedNode && nodeDef ? (
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-3">
          <div className="flex min-w-0 items-center gap-2 text-[var(--text-primary)]">
            <div className={cn('shrink-0 rounded-md p-1', nodeDef.style.bg, nodeDef.style.color)}>
              <NodeIcon size={14} />
            </div>
            {isEditingName ? (
              <input
                autoFocus
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={commitName}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') e.currentTarget.blur()
                  if (e.key === 'Escape') setIsEditingName(false)
                }}
                className="h-6 min-w-0 flex-1 truncate rounded-sm border border-[var(--brand-300)] bg-transparent px-1 text-sm font-semibold outline-none focus:ring-1 focus:ring-[var(--brand-400)]"
              />
            ) : (
              <span
                className={cn(
                  'truncate text-sm font-semibold',
                  userPermissions.canEdit &&
                    'cursor-text rounded-sm px-1 hover:bg-[var(--surface-2)]',
                )}
                onClick={startEditingName}
              >
                {nodeData?.label || nodeDef.label}
              </span>
            )}
            <span className="shrink-0 rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
              {nodeDef.label}
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => selectNode(null)}
            className="h-7 w-7 text-[var(--text-disabled)] hover:bg-[var(--surface-2)] hover:text-[var(--text-secondary)]"
            aria-label={t('workspace.closePanel', { defaultValue: 'Close panel' })}
          >
            <X size={16} />
          </Button>
        </div>
      ) : (
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-[var(--border)] px-3">
          <span className="text-sm font-semibold">{edgeTitle}</span>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={14} />
          </Button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {selectedNode && (
          <PropertiesPanel
            embedded
            node={selectedNode}
            nodes={nodes}
            edges={edges}
            onUpdate={(id, data) => {
              if (!userPermissions.canEdit) {
                denyEdit()
                return
              }
              takeSnapshot()
              const nodeData = selectedNode.data as { label?: string }
              if (data.label !== nodeData.label) updateNodeLabel(id, data.label)
              if (data.config) updateNodeConfig(id, data.config)
            }}
            onClose={() => selectNode(null)}
          />
        )}
        {selectedEdge && (
          <EdgePropertiesPanel
            embedded
            edge={selectedEdge}
            nodes={nodes}
            edges={edges}
            onUpdate={(id, data) => {
              if (!userPermissions.canEdit) {
                denyEdit()
                return
              }
              takeSnapshot()
              updateEdge(id, data)
            }}
            onDelete={(id) => {
              if (!userPermissions.canEdit) {
                denyEdit()
                return
              }
              takeSnapshot()
              onEdgesChange([{ type: 'remove', id }])
              selectEdge(null)
            }}
            onClose={() => selectEdge(null)}
          />
        )}
      </div>
    </div>
  )
}

'use client'

import { Settings2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'

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

  const title = selectedNode
    ? (selectedNode.data as { label?: string })?.label ||
      t('agents.studio.rightPanel.inspector', { defaultValue: 'Inspector' })
    : selectedEdge
      ? t('agents.studio.rightPanel.edgeInspector', { defaultValue: 'Edge Inspector' })
      : ''

  const denyEdit = () =>
    toast({
      title: t('workspace.noPermission'),
      description: t('workspace.cannotEditNode'),
      variant: 'destructive',
    })

  return (
    <div className="flex h-full flex-col bg-[var(--surface-1)]">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-[var(--border)] px-3">
        <div className="flex items-center gap-2">
          <Settings2 size={15} />
          <span className="text-sm font-semibold">{title}</span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose} aria-label="Close">
          <X size={14} />
        </Button>
      </div>

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

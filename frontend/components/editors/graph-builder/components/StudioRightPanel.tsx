'use client'

import { Settings2, Sparkles } from 'lucide-react'

import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'

import { useBuilderStore } from '../stores/builderStore'
import { CopilotPanel } from './CopilotPanel'
import { EdgePropertiesPanel } from './EdgePropertiesPanel'
import PropertiesPanel from './PropertiesPanel'

export function StudioRightPanel() {
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
  } = useBuilderStore()

  const selectedNode = nodes.find((node) => node.id === selectedNodeId)
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId)

  const denyEdit = () =>
    toast({
      title: t('workspace.noPermission'),
      description: t('workspace.cannotEditNode'),
      variant: 'destructive',
    })

  if (selectedNode) {
    return (
      <section className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
          <Settings2 size={15} />
          <span className="text-sm font-semibold">
            {t('agents.studio.rightPanel.inspector', { defaultValue: 'Inspector' })}
          </span>
        </div>
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
      </section>
    )
  }

  if (selectedEdge) {
    return (
      <section className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
          <Settings2 size={15} />
          <span className="text-sm font-semibold">
            {t('agents.studio.rightPanel.edgeInspector', { defaultValue: 'Edge Inspector' })}
          </span>
        </div>
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
      </section>
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface-2)]">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
        <Sparkles size={15} />
        <span className="text-sm font-semibold">
          {t('agents.studio.rightPanel.copilot', { defaultValue: 'Copilot Builder' })}
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <CopilotPanel />
      </div>
    </section>
  )
}

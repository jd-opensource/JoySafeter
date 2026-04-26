'use client'

import { BuilderCanvas } from './components/BuilderCanvas'
import { CopilotOverlay } from './components/CopilotOverlay'
import { GraphStatusBar } from './components/GraphStatusBar'
import { GraphToolbar } from './components/GraphToolbar'
import { InspectorPanel } from './components/InspectorPanel'
import { useBuilderStore } from './stores/builderStore'
import { useBuilderUIStore } from './stores/builderUIStore'

interface GraphBuilderShellProps {
  agentId: string
  versionId?: string
  workspaceId: string
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}

export function GraphBuilderShell({
  agentId,
  onOpenTestLab,
  onOpenRelease,
}: GraphBuilderShellProps) {
  const selectedNodeId = useBuilderStore((s) => s.selectedNodeId)
  const selectedEdgeId = useBuilderStore((s) => s.selectedEdgeId)
  const clearSelection = useBuilderStore((s) => s.selectNode)
  const hasSelection = Boolean(selectedNodeId || selectedEdgeId)

  const copilotExpanded = useBuilderUIStore((s) => s.copilotExpanded)
  const toggleCopilot = useBuilderUIStore((s) => s.toggleCopilot)

  return (
    <div className="flex h-full flex-col">
      <GraphToolbar onOpenTestLab={onOpenTestLab} onOpenRelease={onOpenRelease} />

      <div className="relative flex min-h-0 flex-1">
        {/* Canvas */}
        <div className="min-w-0 flex-1">
          <BuilderCanvas />
        </div>

        {/* Inspector — slides in from right when node/edge selected */}
        {hasSelection && (
          <aside className="w-[360px] shrink-0 overflow-y-auto border-l border-[var(--border)]">
            <InspectorPanel onClose={() => clearSelection(null)} />
          </aside>
        )}

        {/* Copilot — floating overlay */}
        <CopilotOverlay agentId={agentId} expanded={copilotExpanded} onToggle={toggleCopilot} />
      </div>

      <GraphStatusBar />
    </div>
  )
}

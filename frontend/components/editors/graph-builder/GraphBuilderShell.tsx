'use client'

import { useEffect, type ReactNode } from 'react'

import { BuilderCanvas } from './components/BuilderCanvas'
import { CopilotOverlay } from './components/CopilotOverlay'
import { GraphStatusBar } from './components/GraphStatusBar'
import { GraphToolbar } from './components/GraphToolbar'
import { InspectorPanel } from './components/InspectorPanel'
import { useGraphStore } from './stores/graphStore'
import { useBuilderUIStore } from './stores/builderUIStore'

interface GraphBuilderShellProps {
  agentId: string
  onToolbarSlot?: (slot: ReactNode) => void
}

export function GraphBuilderShell({
  agentId,
  onToolbarSlot,
}: GraphBuilderShellProps) {
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId)
  const selectedEdgeId = useGraphStore((s) => s.selectedEdgeId)
  const clearSelection = useGraphStore((s) => s.selectNode)
  const hasSelection = Boolean(selectedNodeId || selectedEdgeId)

  const copilotExpanded = useBuilderUIStore((s) => s.copilotExpanded)
  const toggleCopilot = useBuilderUIStore((s) => s.toggleCopilot)

  useEffect(() => {
    if (onToolbarSlot) {
      onToolbarSlot(<GraphToolbar />)
    }
    return () => {
      if (onToolbarSlot) onToolbarSlot(null)
    }
  }, [onToolbarSlot])

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <BuilderCanvas />
        </div>

        {hasSelection && (
          <aside className="w-[360px] shrink-0 overflow-y-auto border-l border-[var(--border)]">
            <InspectorPanel onClose={() => clearSelection(null)} />
          </aside>
        )}

        <CopilotOverlay agentId={agentId} expanded={copilotExpanded} onToggle={toggleCopilot} />
      </div>

      <GraphStatusBar />
    </div>
  )
}

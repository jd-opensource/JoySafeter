'use client'

import { Bot, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
import { useMemo, useCallback } from 'react'
import ReactFlow, {
  ReactFlowProvider,
  Handle,
  Position,
  useReactFlow,
  type Node,
  type Edge,
  type NodeTypes,
} from 'reactflow'

import 'reactflow/dist/style.css'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { GraphVersionState } from '@/services/graphDeploymentService'

import { nodeRegistry } from '../services/nodeRegistry'

interface GraphPreviewProps {
  state: GraphVersionState | null
  height?: string | number
  width?: string | number
  className?: string
}

/**
 * Simplified preview node component
 */
const PreviewNode = ({
  data,
}: {
  data: { type: string; label?: string; config?: Record<string, unknown> }
}) => {
  const def = nodeRegistry.get(data.type)
  const Icon = def?.icon || Bot
  const colorClass = def?.style?.color || 'text-[var(--text-tertiary)]'
  const bgClass = def?.style?.bg || 'bg-[var(--surface-1)]'
  const label = data.label || def?.label || 'Node'

  return (
    <div className="relative min-w-[100px] rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-2 shadow-sm">
      {/* Left input connection point */}
      <Handle
        type="target"
        position={Position.Left}
        className="!-left-[4px] !h-1.5 !w-1.5 !border-0 !bg-[var(--surface-7)]"
      />

      <div className="flex items-center gap-2">
        <div className={cn('shrink-0 rounded-md border border-black/5 p-1', bgClass, colorClass)}>
          <Icon size={12} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-micro font-semibold text-[var(--text-primary)]">{label}</div>
          <div className="text-[7px] uppercase tracking-wider text-[var(--text-muted)]">
            {def?.subLabel || data.type}
          </div>
        </div>
      </div>

      {/* Right output connection point */}
      <Handle
        type="source"
        position={Position.Right}
        className="!-right-[4px] !h-1.5 !w-1.5 !border-0 !bg-[var(--surface-7)]"
      />
    </div>
  )
}

const nodeTypes: NodeTypes = {
  custom: PreviewNode,
}

/**
 * Internal preview component (with control buttons)
 */
function PreviewContent({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) {
  const { zoomIn, zoomOut, fitView } = useReactFlow()

  const handleZoomIn = useCallback(() => {
    zoomIn({ duration: 200 })
  }, [zoomIn])

  const handleZoomOut = useCallback(() => {
    zoomOut({ duration: 200 })
  }, [zoomOut])

  const handleFitView = useCallback(() => {
    fitView({ padding: 0.3, duration: 200 })
  }, [fitView])

  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        panOnScroll={true}
        panOnDrag={true}
        zoomOnScroll={true}
        zoomOnPinch={true}
        zoomOnDoubleClick={true}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      />

      {/* Control buttons */}
      <div className="absolute bottom-2 right-2 flex items-center gap-0.5 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] p-0.5 shadow-sm">
        <Button
          size="sm"
          variant="ghost"
          className="h-5 w-5 p-0"
          onClick={handleZoomIn}
          title="Zoom in"
        >
          <ZoomIn size={12} />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-5 w-5 p-0"
          onClick={handleZoomOut}
          title="Zoom out"
        >
          <ZoomOut size={12} />
        </Button>
        <div className="h-3 w-px bg-[var(--border)]" />
        <Button
          size="sm"
          variant="ghost"
          className="h-5 w-5 p-0"
          onClick={handleFitView}
          title="Fit view"
        >
          <Maximize2 size={12} />
        </Button>
      </div>
    </>
  )
}

export function GraphPreview({
  state,
  height = 300,
  width = '100%',
  className,
}: GraphPreviewProps) {
  const nodes: Node[] = useMemo(() => {
    if (!state?.nodes) return []

    return state.nodes.map((node) => ({
      id: node.id,
      type: 'custom',
      position: node.position || { x: 0, y: 0 },
      data: node.data || {},
      draggable: false,
      selectable: false,
    }))
  }, [state?.nodes])

  const edges: Edge[] = useMemo(() => {
    if (!state?.edges) return []

    // Deduplicate: avoid React key conflicts
    const seen = new Set<string>()
    const result: Edge[] = []

    for (const edge of state.edges) {
      const id = edge.id || `edge-${edge.source}-${edge.target}`
      // Use source-target combination as unique identifier
      const key = `${edge.source}-${edge.target}`

      if (seen.has(key)) continue
      seen.add(key)

      result.push({
        id,
        source: edge.source,
        target: edge.target,
        type: 'default', // Use Bezier curves to avoid SmoothStep's strange corners
        animated: true,
        style: { stroke: 'var(--edge-color)', strokeWidth: 1.5 },
      })
    }

    return result
  }, [state?.edges])

  if (!state || nodes.length === 0) {
    return (
      <div
        style={{ height, width }}
        className={cn(
          'flex items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-1)]',
          className,
        )}
      >
        <span className="text-xs text-[var(--text-muted)]">No node data</span>
      </div>
    )
  }

  return (
    <ReactFlowProvider>
      <div
        style={{ height, width }}
        className={cn('relative overflow-hidden rounded-lg border border-[var(--border)]', className)}
      >
        <PreviewContent nodes={nodes} edges={edges} />
      </div>
    </ReactFlowProvider>
  )
}

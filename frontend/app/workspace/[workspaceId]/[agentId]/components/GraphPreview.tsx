'use client'

import React, { useMemo, useCallback } from 'react'
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
import { cn } from '@/lib/core/utils/cn'
import type { GraphVersionState } from '@/services/graphDeploymentService'

import { nodeRegistry } from '../services/nodeRegistry'

import { Bot, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

interface GraphPreviewProps {
  state: GraphVersionState | null
  height?: string | number
  width?: string | number
  className?: string
}

/**
 * Simplified preview node component
 */
const PreviewNode = ({ data }: { data: { type: string; label?: string; config?: Record<string, unknown> } }) => {
  const def = nodeRegistry.get(data.type)
  const Icon = def?.icon || Bot
  const colorClass = def?.style?.color || 'text-gray-500'
  const bgClass = def?.style?.bg || 'bg-gray-50'
  const label = data.label || def?.label || 'Node'

  return (
    <div className="min-w-[100px] rounded-lg border border-gray-200 bg-white shadow-sm p-2 relative">
      {/* Left input connection point */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-gray-300 !w-1.5 !h-1.5 !-left-[4px] !border-0"
      />

      <div className="flex items-center gap-2">
        <div className={cn('p-1 rounded-md shrink-0 border border-black/5', bgClass, colorClass)}>
          <Icon size={12} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[9px] font-semibold text-gray-900 truncate">
            {label}
          </div>
          <div className="text-[7px] text-gray-400 uppercase tracking-wider">
            {def?.subLabel || data.type}
          </div>
        </div>
      </div>

      {/* Right output connection point */}
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-gray-300 !w-1.5 !h-1.5 !-right-[4px] !border-0"
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
const PreviewContent: React.FC<{
  nodes: Node[]
  edges: Edge[]
}> = ({ nodes, edges }) => {
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
      <div className="absolute bottom-2 right-2 flex items-center gap-0.5 bg-white/90 rounded-md shadow-sm border border-gray-200 p-0.5">
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
        <div className="w-px h-3 bg-gray-200" />
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

export const GraphPreview: React.FC<GraphPreviewProps> = ({
  state,
  height = 300,
  width = '100%',
  className,
}) => {
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
        style: { stroke: '#cbd5e1', strokeWidth: 1.5 },
      })
    }

    return result
  }, [state?.edges])

  if (!state || nodes.length === 0) {
    return (
      <div
        style={{ height, width }}
        className={cn(
          'flex items-center justify-center rounded-lg border border-gray-200 bg-gray-50',
          className
        )}
      >
        <span className="text-xs text-gray-400">No node data</span>
      </div>
    )
  }

  return (
    <ReactFlowProvider>
      <div style={{ height, width }} className={cn('rounded-lg border border-gray-200 overflow-hidden relative', className)}>
        <PreviewContent nodes={nodes} edges={edges} />
      </div>
    </ReactFlowProvider>
  )
}

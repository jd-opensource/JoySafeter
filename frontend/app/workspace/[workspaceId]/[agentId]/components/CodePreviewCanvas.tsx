'use client'

import ReactFlow, { Background, BackgroundVariant, ReactFlowProvider } from 'reactflow'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { nodeTypes, edgeTypes } from '../utils/reactFlowConfig'
import 'reactflow/dist/style.css'

export function CodePreviewCanvas() {
  const preview = useCodeEditorStore((s) => s.preview)
  const parseErrors = useCodeEditorStore((s) => s.parseErrors)

  const nodes = preview?.nodes ?? []
  const edges = preview?.edges ?? []

  // Highlight nodes referenced in errors (if error has a node context)
  const errorNodeIds = new Set<string>()
  for (const e of parseErrors) {
    // Match node names mentioned in error messages
    for (const n of nodes) {
      if (e.message.includes(`'${n.id}'`)) {
        errorNodeIds.add(n.id)
      }
    }
  }

  const styledNodes = nodes.map((n) => ({
    ...n,
    style: errorNodeIds.has(n.id)
      ? { border: '2px solid #ef4444', borderRadius: 8 }
      : undefined,
  }))

  return (
    <ReactFlow
      nodes={styledNodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      panOnDrag={true}
      zoomOnScroll={true}
      fitView
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} />
    </ReactFlow>
  )
}

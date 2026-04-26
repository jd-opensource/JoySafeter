'use client'

import { Plus } from 'lucide-react'
import React, { useCallback, useMemo, useRef, useState, useEffect } from 'react'
import ReactFlow, { Background, BackgroundVariant } from 'reactflow'

import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'

import { useGraphStore } from '../stores/graphStore'
import { EdgeData } from '../types/graph'
import { EDGE_COLORS } from '../utils/edgeStyles'
import { nodeTypes, edgeTypes } from '../utils/reactFlowConfig'

import { CanvasContextMenu } from './CanvasContextMenu'
import { getContextMenuFlowPosition } from './canvasContextMenuPosition'

import 'reactflow/dist/style.css'

export function BuilderCanvas() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const userPermissions = useUserPermissionsContext()
  const {
    nodes,
    edges,
    selectedNodeId,
    selectedEdgeId,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setRfInstance,
    addNode,
    selectNode,
    selectEdge,
    deleteNode,
    duplicateNode,
    takeSnapshot,
    undo,
    redo,
    graphId,
  } = useGraphStore()

  const [isDragOver, setIsDragOver] = useState(false)
  const [contextMenu, setContextMenu] = useState<{
    open: boolean
    screenX: number
    screenY: number
    flowPosition: { x: number; y: number }
  }>({ open: false, screenX: 0, screenY: 0, flowPosition: { x: 0, y: 0 } })
  const reactFlowWrapper = useRef<HTMLDivElement>(null)

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Don't handle shortcuts when user is typing in an input/textarea
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }

      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0
      const ctrlOrCmd = isMac ? event.metaKey : event.ctrlKey

      // Undo: Ctrl+Z / Cmd+Z
      if (ctrlOrCmd && event.key === 'z' && !event.shiftKey) {
        event.preventDefault()
        if (useGraphStore.getState().past.length > 0 && userPermissions.canEdit) {
          undo()
        }
        return
      }

      // Redo: Ctrl+Shift+Z / Cmd+Shift+Z or Ctrl+Y / Cmd+Y
      if ((ctrlOrCmd && event.key === 'z' && event.shiftKey) || (ctrlOrCmd && event.key === 'y')) {
        event.preventDefault()
        if (useGraphStore.getState().future.length > 0 && userPermissions.canEdit) {
          redo()
        }
        return
      }

      // Copy: Ctrl+C / Cmd+C
      if (ctrlOrCmd && event.key === 'c' && selectedNodeId) {
        event.preventDefault()
        // Copy node data to clipboard (for future paste functionality)
        const node = nodes.find((n) => n.id === selectedNodeId)
        if (node) {
          navigator.clipboard.writeText(JSON.stringify(node)).catch(() => {
            // Silent fail
          })
        }
        return
      }

      // Paste: Ctrl+V / Cmd+V
      if (ctrlOrCmd && event.key === 'v') {
        event.preventDefault()
        if (!userPermissions.canEdit) {
          toast({
            title: t('workspace.noPermission'),
            description: t('workspace.cannotEditNode'),
            variant: 'destructive',
          })
          return
        }
        // Paste functionality would require clipboard reading
        // For now, we'll skip this as it requires additional permissions
        return
      }

      // Select All: Ctrl+A / Cmd+A
      if (ctrlOrCmd && event.key === 'a') {
        event.preventDefault()
        // Select all nodes (if needed in future)
        return
      }

      // Delete: Delete or Backspace
      if (
        (event.key === 'Delete' || event.key === 'Backspace') &&
        (selectedNodeId || selectedEdgeId)
      ) {
        event.preventDefault()
        if (!userPermissions.canEdit) {
          toast({
            title: t('workspace.noPermission'),
            description: t('workspace.cannotEditNode'),
            variant: 'destructive',
          })
          return
        }
        if (selectedNodeId) {
          deleteNode(selectedNodeId)
        } else if (selectedEdgeId) {
          // Delete edge
          const edge = edges.find((e) => e.id === selectedEdgeId)
          if (edge) {
            onEdgesChange([{ type: 'remove', id: edge.id }])
          }
        }
        return
      }

      // Escape: Deselect
      if (event.key === 'Escape') {
        selectNode(null)
        selectEdge(null)
        return
      }

      // Duplicate: Ctrl+D / Cmd+D
      if (ctrlOrCmd && event.key === 'd' && selectedNodeId) {
        event.preventDefault()
        if (!userPermissions.canEdit) {
          toast({
            title: t('workspace.noPermission'),
            description: t('workspace.cannotEditNode'),
            variant: 'destructive',
          })
          return
        }
        duplicateNode(selectedNodeId)
        return
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [
    selectedNodeId,
    selectedEdgeId,
    nodes,
    edges,
    userPermissions.canEdit,
    undo,
    redo,
    deleteNode,
    duplicateNode,
    selectNode,
    selectEdge,
    onEdgesChange,
    toast,
    t,
  ])

  // Ensure edges passed to ReactFlow have unique keys to avoid React warnings.
  const uniqueEdges = useMemo(() => {
    const seen = new Set<string>()
    const result: typeof edges = []

    for (const e of edges) {
      const key = e.id || `${e.source}-${e.target}-${e.sourceHandle ?? ''}-${e.targetHandle ?? ''}`

      if (seen.has(key)) continue
      seen.add(key)
      result.push(e)
    }

    return result
  }, [edges])

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    setIsDragOver(true)
  }, [])

  const onDragLeave = useCallback(() => setIsDragOver(false), [])

  const getFlowPositionFromEvent = useCallback((clientX: number, clientY: number) => {
    const instance = useGraphStore.getState().rfInstance
    if (!instance) return { x: 0, y: 0 }
    return getContextMenuFlowPosition(instance.screenToFlowPosition, clientX, clientY)
  }, [])

  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault()
      setIsDragOver(false)

      if (!userPermissions.canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotEditNode'),
          variant: 'destructive',
        })
        return
      }

      const type = event.dataTransfer.getData('application/reactflow')
      const label = event.dataTransfer.getData('application/label')

      if (!type || !reactFlowWrapper.current) return

      const bounds = reactFlowWrapper.current.getBoundingClientRect()
      const instance = useGraphStore.getState().rfInstance

      const position = instance?.screenToFlowPosition({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      }) || { x: 0, y: 0 }

      addNode(type, position, label)
    },
    [addNode, userPermissions.canEdit, toast, t],
  )

  // Process edges for React Flow with unique types and styling
  const processedEdges = useMemo(() => {
    return uniqueEdges.map((edge) => {
      return {
        ...edge,
        type: 'default',
      }
    })
  }, [uniqueEdges])

  return (
    <div
      className="relative h-full flex-1 overflow-hidden bg-[var(--surface-1)]"
      ref={reactFlowWrapper}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onContextMenu={(event) => {
        if (!userPermissions.canEdit) return
        event.preventDefault()
        setContextMenu({
          open: true,
          screenX: event.clientX,
          screenY: event.clientY,
          flowPosition: getFlowPositionFromEvent(event.clientX, event.clientY),
        })
      }}
    >
      <div
        className={`pointer-events-none absolute inset-4 z-50 flex items-center justify-center rounded-xl border-2 border-dashed transition-all duration-200 ${isDragOver ? 'scale-100 border-[var(--brand-500)] bg-[var(--brand-500)] opacity-100 backdrop-blur-[1px]' : 'scale-95 border-transparent opacity-0'}`}
      >
        <div className="flex animate-bounce items-center gap-3 rounded-xl border border-[var(--brand-100)] bg-[var(--surface-elevated)] px-6 py-3 font-medium text-[var(--brand-600)] shadow-xl">
          <Plus size={20} /> <span className="text-lg">{t('workspace.dropToAddNode')}</span>
        </div>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={processedEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onInit={setRfInstance}
        onNodeClick={(_, node) => selectNode(node.id)}
        onEdgeClick={(_, edge) => selectEdge(edge.id)}
        onPaneClick={() => {
          selectNode(null)
          selectEdge(null)
        }}
        onNodeDragStart={() => takeSnapshot()}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        className="h-full w-full bg-[var(--surface-1)]"
        defaultEdgeOptions={{
          style: { stroke: EDGE_COLORS.normal, strokeWidth: 1.5 },
          animated: true,
        }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--canvas-dot)" gap={20} size={1} variant={BackgroundVariant.Dots} />
      </ReactFlow>

      <CanvasContextMenu
        open={contextMenu.open}
        x={contextMenu.screenX}
        y={contextMenu.screenY}
        onClose={() => setContextMenu((current) => ({ ...current, open: false }))}
        onAddNode={(node) => addNode(node.type, contextMenu.flowPosition, node.label)}
      />
    </div>
  )
}

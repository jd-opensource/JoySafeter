'use client'

import { Plus, Undo2, Redo2, ZoomIn, ZoomOut, Maximize } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useCallback, useMemo, useRef, useState, useEffect } from 'react'
import ReactFlow, { Background, BackgroundVariant, useReactFlow } from 'reactflow'

import { useToast } from '@/components/ui/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { useSidebarStore } from '@/stores/sidebar/store'

import { agentService } from '../services/agentService'
import { nodeRegistry } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'
import { EdgeData } from '../types/graph'
import { EDGE_COLORS } from '../utils/edgeStyles'
import { nodeTypes, edgeTypes } from '../utils/reactFlowConfig'

import { EdgePropertiesPanel } from './EdgePropertiesPanel'
import { GraphStatusBar } from './GraphStatusBar'
import PropertiesPanel from './PropertiesPanel'
import { SchemaExportPanel } from './SchemaExportPanel'
import { ValidationSummaryPanel } from './ValidationSummaryPanel'

import 'reactflow/dist/style.css'

// Custom Controls Component
interface CustomControlsProps {
  past: unknown[]
  future: unknown[]
  canEdit: boolean
  onUndo: () => void
  onRedo: () => void
  onPermissionDenied: () => void
  undoTitle: string
  redoTitle: string
  zoomInTitle: string
  zoomOutTitle: string
  fitViewTitle: string
}

function CustomControls({
  past,
  future,
  canEdit,
  onUndo,
  onRedo,
  onPermissionDenied,
  undoTitle,
  redoTitle,
  zoomInTitle,
  zoomOutTitle,
  fitViewTitle,
}: CustomControlsProps) {
  const { zoomIn, zoomOut, fitView } = useReactFlow()

  const handleUndo = () => {
    if (!canEdit) {
      onPermissionDenied()
      return
    }
    onUndo()
  }

  const handleRedo = () => {
    if (!canEdit) {
      onPermissionDenied()
      return
    }
    onRedo()
  }

  return (
    <div className="absolute bottom-4 left-1/2 z-[100] -translate-x-1/2 transform">
      <div className="flex items-center gap-0.5 rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
        {/* Zoom Controls */}
        <button
          onClick={() => zoomIn()}
          className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-gray-100 active:bg-gray-200"
          title={zoomInTitle}
        >
          <ZoomIn size={15} className="text-gray-600" />
        </button>
        <button
          onClick={() => zoomOut()}
          className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-gray-100 active:bg-gray-200"
          title={zoomOutTitle}
        >
          <ZoomOut size={15} className="text-gray-600" />
        </button>
        <button
          onClick={() => fitView({ padding: 0.2 })}
          className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-gray-100 active:bg-gray-200"
          title={fitViewTitle}
        >
          <Maximize size={15} className="text-gray-600" />
        </button>

        {/* Divider */}
        <div className="mx-1 h-5 w-px bg-gray-200" />

        {/* Undo/Redo */}
        <button
          onClick={handleUndo}
          disabled={past.length === 0 || !canEdit}
          className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-gray-100 active:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
          title={undoTitle}
        >
          <Undo2 size={15} className="text-gray-600" />
        </button>
        <button
          onClick={handleRedo}
          disabled={future.length === 0 || !canEdit}
          className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-gray-100 active:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
          title={redoTitle}
        >
          <Redo2 size={15} className="text-gray-600" />
        </button>
      </div>
    </div>
  )
}

export function BuilderCanvas() {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)
  const {
    nodes,
    edges,
    selectedNodeId,
    selectedEdgeId,
    past,
    future,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setRfInstance,
    addNode,
    selectNode,
    selectEdge,
    deleteNode,
    duplicateNode,
    updateNodeConfig,
    updateNodeLabel,
    updateEdge,
    takeSnapshot,
    undo,
    redo,
    graphId,
    showSchemaExport,
    toggleSchemaExport,
    showValidationSummary,
    toggleValidationSummary,
  } = useBuilderStore()

  // Get sidebar state to adjust status bar position
  const isSidebarCollapsed = useSidebarStore((state) => state.isCollapsed)

  const [isDragOver, setIsDragOver] = useState(false)
  const reactFlowWrapper = useRef<HTMLDivElement>(null)

  const selectedNode = nodes.find((n) => n.id === selectedNodeId)

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
        if (past.length > 0 && userPermissions.canEdit) {
          undo()
        }
        return
      }

      // Redo: Ctrl+Shift+Z / Cmd+Shift+Z or Ctrl+Y / Cmd+Y
      if ((ctrlOrCmd && event.key === 'z' && event.shiftKey) || (ctrlOrCmd && event.key === 'y')) {
        event.preventDefault()
        if (future.length > 0 && userPermissions.canEdit) {
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
    past,
    future,
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
      const instance = useBuilderStore.getState().rfInstance

      const position = instance?.screenToFlowPosition({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      }) || { x: 0, y: 0 }

      // If it's an agent node, get the default model
      let configOverride: Record<string, unknown> | undefined
      if (type === 'agent') {
        try {
          const defaultModelId = await agentService.getDefaultModelId()
          if (defaultModelId) {
            const agentDef = nodeRegistry.get('agent')
            configOverride = { ...agentDef?.defaultConfig }
            configOverride.model = defaultModelId
            configOverride.memoryModel = defaultModelId

            // Also populate split fields for backend resolution consistency
            if (typeof defaultModelId === 'string' && defaultModelId.includes(':')) {
              const [providerName, modelName] = defaultModelId.split(':', 2)
              configOverride.provider_name = providerName
              configOverride.model_name = modelName
              configOverride.provider = providerName
              configOverride.memoryProvider = providerName
            }
          }
        } catch (error) {
          console.error('Failed to get default model:', error)
          // If fetching fails, continue with hardcoded default values
        }
      }

      addNode(type, position, label, configOverride)
    },
    [addNode, userPermissions.canEdit, toast, t],
  )

  // Process edges for React Flow with unique types and styling
  const processedEdges = useMemo(() => {
    return uniqueEdges.map((edge) => {
      const edgeData = (edge.data || {}) as EdgeData
      // Set edge type based on edge_type in data
      // LoopBackEdge component handles custom path calculation with offset
      if (edgeData.edge_type === 'loop_back') {
        return {
          ...edge,
          type: 'loop_back',
        }
      }
      // Use DefaultEdge for normal and conditional edges (handles label display)
      return {
        ...edge,
        type: 'default',
      }
    })
  }, [uniqueEdges])

  return (
    <div
      className="relative h-full flex-1 overflow-hidden bg-gray-50"
      ref={reactFlowWrapper}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div
        className={`pointer-events-none absolute inset-4 z-50 flex items-center justify-center rounded-xl border-2 border-dashed transition-all duration-200 ${isDragOver ? 'scale-100 border-blue-500/50 bg-blue-500/5 opacity-100 backdrop-blur-[1px]' : 'scale-95 border-transparent opacity-0'}`}
      >
        <div className="flex animate-bounce items-center gap-3 rounded-xl border border-blue-100 bg-white px-6 py-3 font-medium text-blue-600 shadow-xl">
          <Plus size={20} /> <span className="text-lg">{t('workspace.dropToAddNode')}</span>
        </div>
      </div>

      {/* Status Bar - Top Left */}
      {/* Adjust position based on sidebar state to avoid overlap */}
      {/* Sidebar header when collapsed is at left-[190px] with max-w-[232px], but actual content is narrower */}
      <div
        className="absolute top-4 z-[100]"
        style={{
          left: isSidebarCollapsed ? '320px' : '16px',
        }}
      >
        <GraphStatusBar />
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
        className="h-full w-full bg-gray-50"
        defaultEdgeOptions={{
          style: { stroke: EDGE_COLORS.normal, strokeWidth: 1.5 },
          animated: true,
        }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#cbd5e1" gap={20} size={1} variant={BackgroundVariant.Dots} />
        {/* Custom Controls with Zoom + Undo/Redo - Bottom Center */}
        <CustomControls
          past={past}
          future={future}
          canEdit={userPermissions.canEdit}
          onUndo={undo}
          onRedo={redo}
          onPermissionDenied={() => {
            toast({
              title: t('workspace.noPermission'),
              description: t('workspace.cannotEditNode'),
              variant: 'destructive',
            })
          }}
          undoTitle={t('workspace.undo')}
          redoTitle={t('workspace.redo')}
          zoomInTitle={t('workspace.zoomIn')}
          zoomOutTitle={t('workspace.zoomOut')}
          fitViewTitle={t('workspace.fitView')}
        />
      </ReactFlow>

      {selectedNode && (
        <PropertiesPanel
          node={selectedNode}
          nodes={nodes}
          edges={edges}
          onUpdate={(id, data) => {
            if (!userPermissions.canEdit) {
              toast({
                title: t('workspace.noPermission'),
                description: t('workspace.cannotEditNode'),
                variant: 'destructive',
              })
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

      {selectedEdgeId && (
        <EdgePropertiesPanel
          edge={edges.find((e) => e.id === selectedEdgeId)!}
          nodes={nodes}
          edges={edges}
          onUpdate={(id, data) => {
            if (!userPermissions.canEdit) {
              toast({
                title: t('workspace.noPermission'),
                description: t('workspace.cannotEditNode'),
                variant: 'destructive',
              })
              return
            }
            takeSnapshot()
            updateEdge(id, data)
          }}
          onDelete={(id) => {
            if (!userPermissions.canEdit) {
              toast({
                title: t('workspace.noPermission'),
                description: t('workspace.cannotEditNode'),
                variant: 'destructive',
              })
              return
            }
            takeSnapshot()
            onEdgesChange([{ type: 'remove', id }])
            selectEdge(null)
          }}
          onClose={() => selectEdge(null)}
        />
      )}

      {showSchemaExport && graphId && (
        <SchemaExportPanel
          graphId={graphId}
          open={showSchemaExport}
          onClose={() => toggleSchemaExport(false)}
        />
      )}

      {showValidationSummary && (
        <ValidationSummaryPanel
          nodes={nodes}
          edges={edges}
          onClose={() => toggleValidationSummary(false)}
          onSelectNode={selectNode}
          onSelectEdge={selectEdge}
        />
      )}
    </div>
  )
}

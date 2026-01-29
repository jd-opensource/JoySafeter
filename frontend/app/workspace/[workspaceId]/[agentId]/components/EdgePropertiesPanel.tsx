'use client'

import { X, ArrowRight, AlertCircle, CheckCircle2, Trash2 } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useMemo, useState } from 'react'
import { Node, Edge } from 'reactflow'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { validateEdgeData } from '../services/edgeValidator'
import { EdgeData } from '../types/graph'

interface EdgePropertiesPanelProps {
  edge: Edge
  nodes: Node[]
  edges: Edge[]
  onUpdate: (id: string, data: Partial<EdgeData>) => void
  onDelete?: (id: string) => void
  onClose: () => void
}

export const EdgePropertiesPanel: React.FC<EdgePropertiesPanelProps> = ({
  edge,
  nodes,
  edges,
  onUpdate,
  onDelete,
  onClose,
}) => {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const sourceNode = nodes.find((n) => n.id === edge.source)
  const targetNode = nodes.find((n) => n.id === edge.target)
  const sourceNodeType = (sourceNode?.data as { type?: string })?.type || ''
  const edgeData = (edge.data || {}) as EdgeData

  // Check if source node needs Handle ID mapping
  const isConditionalSource = ['router_node', 'condition', 'loop_condition_node'].includes(
    sourceNodeType
  )

  // Auto-generate Handle ID suggestions based on node type
  const getHandleIdSuggestions = () => {
    if (sourceNodeType === 'router_node') {
      const config = (sourceNode?.data as {
        config?: { routes?: Array<{ targetEdgeKey?: string }> }
      })?.config
      const routes = config?.routes || []
      return routes.map((r) => ({
        handleId: r.targetEdgeKey || '',
        routeKey: r.targetEdgeKey || '',
      }))
    }
    if (sourceNodeType === 'loop_condition_node') {
      return [
        { handleId: 'continue_loop_handle', routeKey: 'continue_loop' },
        { handleId: 'exit_loop_handle', routeKey: 'exit_loop' },
      ]
    }
    if (sourceNodeType === 'condition') {
      return [
        { handleId: 'true_handle', routeKey: 'true' },
        { handleId: 'false_handle', routeKey: 'false' },
      ]
    }
    return []
  }

  const suggestions = getHandleIdSuggestions()

  // Validate edge data
  const validationErrors = useMemo(() => {
    return validateEdgeData(edge, sourceNode, targetNode)
  }, [edge, sourceNode, targetNode])

  const hasErrors = validationErrors.length > 0
  const criticalErrors = validationErrors.filter((e) => e.severity === 'error')

  const updateEdgeData = (updates: Partial<EdgeData>) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }
    onUpdate(edge.id, { ...edgeData, ...updates })
  }

  const handleDelete = () => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }
    if (onDelete) {
      onDelete(edge.id)
      setShowDeleteConfirm(false)
      onClose()
    }
  }

  return (
    <div className="absolute top-[56px] right-[336px] bottom-[60px] w-[400px] bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right-10 fade-in duration-300 z-50">
      {/* Header */}
      <div className="px-4 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white shrink-0">
        <div className="flex items-center gap-3 text-gray-900 overflow-hidden">
          <div className="p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0 bg-blue-50 text-blue-600">
            <ArrowRight size={14} />
          </div>
          <div className="flex flex-col min-w-0">
            <h3 className="font-bold text-sm leading-tight truncate">Edge Properties</h3>
            <span className="text-[9px] text-gray-400 uppercase tracking-widest font-bold">
              Connection
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-7 w-7 text-gray-300 hover:text-gray-600 hover:bg-gray-100 shrink-0"
        >
          <X size={16} />
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4 pb-12">
        {/* Source -> Target Display */}
        <div className="flex items-center gap-2 text-xs text-gray-500 pb-2 border-b border-gray-100">
          <Badge variant="outline" className="text-[10px]">
            {(sourceNode?.data as { label?: string })?.label || sourceNode?.id}
          </Badge>
          <ArrowRight size={12} />
          <Badge variant="outline" className="text-[10px]">
            {(targetNode?.data as { label?: string })?.label || targetNode?.id}
          </Badge>
        </div>

        {/* Validation Errors */}
        {hasErrors && (
          <div className="space-y-1">
            {validationErrors.map((error, idx) => (
              <div
                key={idx}
                className={cn(
                  'flex items-start gap-2 p-2 rounded text-xs',
                  error.severity === 'error'
                    ? 'bg-red-50 border border-red-200'
                    : 'bg-amber-50 border border-amber-200'
                )}
              >
                <AlertCircle
                  size={14}
                  className={cn(
                    'mt-0.5 flex-shrink-0',
                    error.severity === 'error' ? 'text-red-600' : 'text-amber-600'
                  )}
                />
                <div className={cn(error.severity === 'error' ? 'text-red-800' : 'text-amber-800')}>
                  <div className="font-medium">{error.field}</div>
                  <div className="text-xs mt-0.5">{error.message}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Validation Success */}
        {!hasErrors && edgeData.edge_type && (
          <div className="flex items-center gap-2 p-2 bg-green-50 border border-green-200 rounded text-xs text-green-800">
            <CheckCircle2 size={14} />
            <span>Edge configuration is valid</span>
          </div>
        )}

        {/* Edge Type */}
        <div className="space-y-1.5">
          <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
            Edge Type
          </Label>
          <Select
            value={edgeData.edge_type || 'normal'}
            onValueChange={(v) => updateEdgeData({ edge_type: v as EdgeData['edge_type'] })}
            disabled={!userPermissions.canEdit}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="normal">Normal</SelectItem>
              <SelectItem value="conditional">Conditional</SelectItem>
              <SelectItem value="loop_back">Loop Back</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-[9px] text-gray-400">
            Normal: standard connection | Conditional: route based on condition | Loop Back: loop iteration (purple dashed line, supports manual path adjustment)
          </p>
        </div>

        {/* Route Key (only for conditional edges from router/condition nodes) */}
        {isConditionalSource && edgeData.edge_type === 'conditional' && (
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
              Route Key
            </Label>
            <Input
              value={edgeData.route_key || ''}
              onChange={(e) => updateEdgeData({ route_key: e.target.value })}
              placeholder="e.g., high_score, default"
              disabled={!userPermissions.canEdit}
              className="h-8 text-xs"
            />
            <p className="text-[9px] text-gray-400">
              Must match a route key defined in the source node
            </p>

            {/* Suggestions */}
            {suggestions.length > 0 && (
              <div className="space-y-1">
                <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                  Quick Select
                </Label>
                <div className="space-y-1">
                  {suggestions.map((suggestion, idx) => (
                    <button
                      key={idx}
                      onClick={() => {
                        updateEdgeData({
                          route_key: suggestion.routeKey,
                          source_handle_id: suggestion.handleId,
                        })
                      }}
                      disabled={!userPermissions.canEdit}
                      className={cn(
                        'w-full text-left px-2 py-1.5 text-xs rounded border transition-colors',
                        'hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed',
                        edgeData.route_key === suggestion.routeKey
                          ? 'border-blue-300 bg-blue-50'
                          : 'border-gray-200'
                      )}
                    >
                      <div className="font-medium">{suggestion.routeKey}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Source Handle ID (for conditional edges) */}
        {isConditionalSource && edgeData.edge_type === 'conditional' && (
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
              Source Handle ID
            </Label>
            <Input
              value={edgeData.source_handle_id || ''}
              onChange={(e) => updateEdgeData({ source_handle_id: e.target.value })}
              placeholder="e.g. yes_handle, no_handle"
              disabled={!userPermissions.canEdit}
              className="h-8 text-xs"
            />
            <p className="text-[9px] text-gray-400">
              React Flow handle ID (optional, for advanced use cases)
            </p>
          </div>
        )}

        {/* Edge Label */}
        <div className="space-y-1.5">
          <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
            Label (optional)
          </Label>
          <Input
            value={edgeData.label || ''}
            onChange={(e) => updateEdgeData({ label: e.target.value })}
            placeholder="Display label on edge"
            disabled={!userPermissions.canEdit}
            className="h-8 text-xs"
          />
          <p className="text-[9px] text-gray-400">Optional display label for the edge</p>
        </div>
      </div>

      {/* Footer Actions */}
      <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[9px] text-gray-400 font-mono">
          <span className="truncate">EDGE: {edge.id.slice(0, 8)}</span>
          <span className="flex items-center gap-1">
            <div className={cn('w-1.5 h-1.5 rounded-full', hasErrors ? 'bg-red-500' : 'bg-green-500')} />{' '}
            {hasErrors ? 'Issues' : 'Valid'}
          </span>
        </div>
        {onDelete && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={!userPermissions.canEdit}
            className="h-7 px-2 text-red-600 hover:text-red-700 hover:bg-red-50 text-xs"
          >
            <Trash2 size={12} className="mr-1" />
            删除
          </Button>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      {onDelete && (
        <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
          <AlertDialogContent variant="destructive">
            <AlertDialogHeader>
              <AlertDialogTitle>删除连接</AlertDialogTitle>
              <AlertDialogDescription>
                确定要删除这条连接吗？此操作无法撤销。
                <br />
                <span className="text-xs text-gray-500 mt-1 block">
                  从 <strong>{(sourceNode?.data as { label?: string })?.label || edge.source}</strong> 到{' '}
                  <strong>{(targetNode?.data as { label?: string })?.label || edge.target}</strong>
                </span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => setShowDeleteConfirm(false)}>
                取消
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={handleDelete}
                className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
              >
                删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  )
}

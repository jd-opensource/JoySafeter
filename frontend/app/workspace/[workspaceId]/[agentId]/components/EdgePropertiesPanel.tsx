'use client'

import {
  X,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
  Trash2,
  Split,
  Route,
  Repeat2,
} from 'lucide-react'
import { useParams } from 'next/navigation'
import { useMemo, useState } from 'react'
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
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { Textarea } from '@/components/ui/textarea'

import { useBuilderStore } from '../stores/builderStore'
import { EdgeData } from '../types/graph'

interface EdgePropertiesPanelProps {
  edge: Edge
  nodes: Node[]
  edges: Edge[]
  onUpdate: (id: string, data: Partial<EdgeData>) => void
  onDelete?: (id: string) => void
  onClose: () => void
}

export function EdgePropertiesPanel({
  edge,
  nodes,
  edges: _edges,
  onUpdate,
  onDelete,
  onClose,
}: EdgePropertiesPanelProps) {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Store actions for smart updates
  const updateNodeConfig = useBuilderStore((state) => state.updateNodeConfig)
  const graphStateFields = useBuilderStore((state) => state.graphStateFields)

  const sourceNode = nodes.find((n) => n.id === edge.source)
  const targetNode = nodes.find((n) => n.id === edge.target)
  const sourceNodeType = (sourceNode?.data as { type?: string })?.type || ''
  const edgeData = useMemo(() => (edge.data || {}) as EdgeData, [edge.data])

  // Check if source node needs Handle ID mapping
  const isRouterNode = sourceNodeType === 'router_node'
  const isConditionNode = sourceNodeType === 'condition'
  const isLoopNode = sourceNodeType === 'loop_condition_node'
  const isConditionalSource = isRouterNode || isConditionNode || isLoopNode

  // --- Smart Condition Logic ---

  // Get the current condition from the source node configuration
  const currentCondition = useMemo(() => {
    if (!sourceNode?.data?.config) return ''
    const config = sourceNode.data.config as any

    if (isRouterNode) {
      // Find the route that matches this edge's route_key
      const route = config.routes?.find((r: any) => r.targetEdgeKey === edgeData.route_key)
      return route?.condition || ''
    }

    if (isConditionNode) {
      // Both True and False branches share the same expression
      return config.expression || ''
    }

    if (isLoopNode) {
      return config.condition || ''
    }

    return ''
  }, [sourceNode, isRouterNode, isConditionNode, isLoopNode, edgeData.route_key])

  // Handler to update source node condition
  const handleConditionChange = (newCondition: string) => {
    if (!sourceNode || !userPermissions.canEdit) return
    const config = { ...(sourceNode.data.config as any) }

    if (isRouterNode) {
      if (!config.routes) return
      // Update specific route
      config.routes = config.routes.map((r: any) => {
        if (r.targetEdgeKey === edgeData.route_key) {
          return { ...r, condition: newCondition }
        }
        return r
      })
    } else if (isConditionNode) {
      config.expression = newCondition
    } else if (isLoopNode) {
      config.condition = newCondition
    }

    updateNodeConfig(sourceNode.id, config)
  }

  // --- End Smart Logic ---

  // Auto-generate Handle ID suggestions based on node type
  const getHandleIdSuggestions = () => {
    if (sourceNodeType === 'router_node') {
      const config = (
        sourceNode?.data as {
          config?: { routes?: Array<{ targetEdgeKey?: string }> }
        }
      )?.config
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
    const errors: { field: string; message: string; severity?: string }[] = []

    // Check conditional edges
    if (edgeData.edge_type === 'conditional') {
      if (!edgeData.route_key) {
        errors.push({
          field: 'Route Key',
          message: t('workspace.routeKeyRequired', { defaultValue: 'Route key is required' }),
          severity: 'error',
        })
      } else {
        // Validate route key exists in source node config
        if (sourceNodeType === 'router_node') {
          const config = (
            sourceNode?.data as { config?: { routes?: Array<{ targetEdgeKey?: string }> } }
          )?.config
          const routes = config?.routes || []
          const ruleExists = routes.some((r) => r.targetEdgeKey === edgeData.route_key)

          if (!ruleExists) {
            errors.push({
              field: 'Route Key',
              message: t('workspace.routeKeyMismatch', {
                defaultValue: 'Route key must match a rule in the source node',
              }),
              severity: 'warning',
            })
          }
        }
      }
    }

    return errors
  }, [edgeData, sourceNode, sourceNodeType, t])

  const hasErrors = validationErrors.length > 0

  // Decide if we should show the smart condition editor
  // Show if: Source is Conditional Type AND Edge is Conditional AND (RouteKey is set OR not router)
  // For Router: need route_key to know WHICH condition to edit
  const showSmartEditor =
    isConditionalSource &&
    edgeData.edge_type === 'conditional' &&
    (!isRouterNode || edgeData.route_key)

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

  const getSourceIcon = () => {
    if (isRouterNode) return <Route size={14} className="text-orange-500" />
    if (isConditionNode) return <Split size={14} className="text-amber-500" />
    if (isLoopNode) return <Repeat2 size={14} className="text-cyan-500" />
    return null
  }

  return (
    <div className="absolute bottom-[60px] right-[336px] top-[56px] z-50 flex w-[400px] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-2xl duration-300 animate-in fade-in slide-in-from-right-10">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-1)] px-4 py-3.5">
        <div className="flex items-center gap-3 overflow-hidden text-[var(--text-primary)]">
          <div className="shrink-0 rounded-lg border border-[var(--border-muted)] bg-[var(--brand-50)] p-1.5 text-[var(--brand-500)] shadow-sm">
            <ArrowRight size={14} />
          </div>
          <div className="flex min-w-0 flex-col">
            <h3 className="truncate text-sm font-bold leading-tight">Edge Properties</h3>
            <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              Connection
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-7 w-7 shrink-0 text-[var(--text-subtle)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
        >
          <X size={16} />
        </Button>
      </div>

      {/* Body */}
      <div className="custom-scrollbar flex-1 space-y-4 overflow-y-auto p-4 pb-12">
        {/* Source -> Target Display */}
        <div className="flex items-center gap-2 border-b border-[var(--border-muted)] pb-2 text-xs text-[var(--text-tertiary)]">
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
                  'flex items-start gap-2 rounded p-2 text-xs',
                  error.severity === 'error'
                    ? 'border border-red-200 bg-red-50'
                    : 'border border-amber-200 bg-amber-50',
                )}
              >
                <AlertCircle
                  size={14}
                  className={cn(
                    'mt-0.5 flex-shrink-0',
                    error.severity === 'error' ? 'text-red-600' : 'text-amber-600',
                  )}
                />
                <div className={cn(error.severity === 'error' ? 'text-red-800' : 'text-amber-800')}>
                  <div className="font-medium">{error.field}</div>
                  <div className="mt-0.5 text-xs">{error.message}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Validation Success */}
        {!hasErrors && edgeData.edge_type && (
          <div className="flex items-center gap-2 rounded border border-green-200 bg-green-50 p-2 text-xs text-green-800">
            <CheckCircle2 size={14} />
            <span>Edge configuration is valid</span>
          </div>
        )}

        {/* Smart Condition Editor */}
        {showSmartEditor && (
          <div className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3">
            <div className="mb-1 flex items-center gap-2">
              {getSourceIcon()}
              <Label className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-tertiary)]">
                Logic Condition ({sourceNodeType.replace('_node', '')})
              </Label>
            </div>
            <p className="mb-2 text-[10px] text-[var(--text-muted)]">
              {isRouterNode
                ? `Edits condition for route "${edgeData.route_key}"`
                : isConditionNode
                  ? 'Edits the splitting condition'
                  : 'Edits the loop continue condition'}
            </p>
            <Textarea
              value={currentCondition}
              onChange={(e) => handleConditionChange(e.target.value)}
              disabled={!userPermissions.canEdit}
              placeholder={
                isRouterNode
                  ? "state.get('value') > 10"
                  : isConditionNode
                    ? "state.get('is_valid')"
                    : 'loop_count < 5'
              }
              className="min-h-[60px] font-mono text-xs"
            />
            <div className="mt-1 flex items-center gap-1.5 text-[9px] text-blue-600/70">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
              Updates Source Node Configuration
            </div>
          </div>
        )}

        {/* Route Key (Smart Select) */}
        {isConditionalSource && (
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Route Key
            </Label>

            {suggestions.length > 0 ? (
              <Select
                value={edgeData.route_key || ''}
                onValueChange={(val) => {
                  const suggestion = suggestions.find((s) => s.routeKey === val)
                  updateEdgeData({
                    route_key: val,
                    source_handle_id: suggestion?.handleId || val, // Auto-map handle ID
                    edge_type: 'conditional', // Force conditional type
                  })
                }}
                disabled={!userPermissions.canEdit}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Select a route..." />
                </SelectTrigger>
                <SelectContent>
                  {suggestions.map((s, idx) => (
                    <SelectItem key={idx} value={s.routeKey}>
                      {s.routeKey}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                value={edgeData.route_key || ''}
                onChange={(e) =>
                  updateEdgeData({
                    route_key: e.target.value,
                    edge_type: 'conditional',
                  })
                }
                placeholder="e.g., high_score, default"
                disabled={!userPermissions.canEdit}
                className="h-8 text-xs"
              />
            )}

            <p className="text-[9px] text-[var(--text-muted)]">
              {isRouterNode
                ? 'Select a route defined in the source node'
                : 'Logic branch for this connection'}
            </p>
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="flex items-center justify-between border-t border-[var(--border-muted)] bg-[var(--surface-1)] px-4 py-2">
        <div className="flex items-center gap-2 font-mono text-[9px] text-[var(--text-muted)]">
          <span className="truncate">EDGE: {edge.id.slice(0, 8)}</span>
          <span className="flex items-center gap-1">
            <div
              className={cn('h-1.5 w-1.5 rounded-full', hasErrors ? 'bg-red-500' : 'bg-green-500')}
            />{' '}
            {hasErrors ? 'Issues' : 'Valid'}
          </span>
        </div>
        {onDelete && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={!userPermissions.canEdit}
            className="h-7 px-2 text-xs text-red-600 hover:bg-red-50 hover:text-red-700"
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
                <span className="mt-1 block text-xs text-[var(--text-tertiary)]">
                  从{' '}
                  <strong>{(sourceNode?.data as { label?: string })?.label || edge.source}</strong>{' '}
                  到{' '}
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

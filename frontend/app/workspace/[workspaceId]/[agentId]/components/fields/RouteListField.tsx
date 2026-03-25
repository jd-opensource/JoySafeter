'use client'

import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Plus, Trash2, AlertCircle, CheckCircle2, ArrowRight } from 'lucide-react'
import React, { useMemo } from 'react'
import { Node, Edge } from 'reactflow'

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
import { cn } from '@/lib/utils'
import { generateUUID } from '@/lib/utils/uuid'

import { RouteRule, EdgeData } from '../../types/graph'

import { ConditionExprField } from './ConditionExprField'

// Inline validation to avoid dependency on removed validator file
const validateRouteRuleEdgeMatch = (
  rule: RouteRule,
  edges: Edge[],
  nodeId: string,
): { message: string }[] => {
  const errors: { message: string }[] = []

  if (!rule.targetEdgeKey) {
    errors.push({ message: 'Target edge is required' })
    return errors
  }

  // Find outgoing edges from this node
  const outgoingEdges = edges.filter((e) => e.source === nodeId)

  // Check if any edge matches the route key
  const hasMatchingEdge = outgoingEdges.some((edge) => {
    const edgeData = (edge.data || {}) as EdgeData
    // Match logic: edge.data.route_key OR edge.id
    const routeKey =
      edgeData.route_key && edgeData.route_key.trim() !== '' ? edgeData.route_key : edge.id

    return routeKey === rule.targetEdgeKey
  })

  if (!hasMatchingEdge) {
    errors.push({ message: 'No matching edge found for this route' })
  }

  return errors
}

interface RouteListFieldProps {
  value: RouteRule[]
  onChange: (rules: RouteRule[]) => void
  availableEdges: Edge[]
  targetNodes: Node[]
  currentNodeId: string
  nodes: Node[]
  edges: Edge[]
  onCreateEdge?: (targetNodeId: string, routeKey: string) => void
  graphStateFields?: import('../../types/graph').StateField[]
}

interface RouteRuleItemProps {
  rule: RouteRule
  index: number
  availableEdges: Edge[]
  targetNodes: Node[]
  currentNodeId: string
  nodes: Node[]
  edges: Edge[]
  onUpdate: (rule: RouteRule) => void
  onDelete: () => void
  onCreateEdge?: (targetNodeId: string, routeKey: string) => void
  graphStateFields?: import('../../types/graph').StateField[]
}

function RouteRuleItem({
  rule,
  index,
  availableEdges,
  targetNodes,
  currentNodeId,
  nodes,
  edges,
  onUpdate,
  onDelete,
  onCreateEdge,
  graphStateFields,
}: RouteRuleItemProps) {
  const [selectedTargetNodeId, setSelectedTargetNodeId] = React.useState<string>('')
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: rule.id,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  // Get edge options for select dropdown
  const edgeOptions = useMemo(() => {
    return availableEdges.map((edge) => {
      const edgeData = (edge.data || {}) as EdgeData
      const targetNode = targetNodes.find((n) => n.id === edge.target)
      const targetLabel =
        (targetNode?.data as { label?: string })?.label || targetNode?.id || edge.target
      // Ensure routeKey is never empty string - use edgeId as fallback
      const routeKey =
        edgeData.route_key && edgeData.route_key.trim() !== '' ? edgeData.route_key : edge.id

      return {
        edgeId: edge.id,
        routeKey,
        label: edgeData.label || targetLabel,
        displayText:
          routeKey && routeKey !== edge.id ? `${routeKey} → ${targetLabel}` : targetLabel,
      }
    })
  }, [availableEdges, targetNodes])

  // Validate this rule
  const validationErrors = useMemo(() => {
    return validateRouteRuleEdgeMatch(rule, edges, currentNodeId)
  }, [rule, edges, currentNodeId])

  const hasErrors = validationErrors.length > 0

  const handleFieldChange = (field: keyof RouteRule, newValue: string) => {
    onUpdate({ ...rule, [field]: newValue })
  }

  const handleEdgeSelect = (edgeId: string) => {
    const selectedEdge = availableEdges.find((e) => e.id === edgeId)
    if (selectedEdge) {
      const edgeData = (selectedEdge.data || {}) as EdgeData
      // Use route_key if available and not empty, otherwise use edgeId
      const routeKey =
        edgeData.route_key && edgeData.route_key.trim() !== '' ? edgeData.route_key : edgeId
      onUpdate({
        ...rule,
        targetEdgeKey: routeKey,
      })
    }
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        'space-y-3 rounded-lg border bg-[var(--surface-elevated)] p-3',
        hasErrors && 'border-red-200 bg-red-50/30',
        isDragging && 'shadow-lg',
      )}
    >
      <div className="flex items-start gap-2">
        {/* Drag Handle */}
        <button
          {...attributes}
          {...listeners}
          className="mt-1 cursor-grab text-[var(--text-muted)] hover:text-[var(--text-secondary)] active:cursor-grabbing"
        >
          <GripVertical size={16} />
        </button>

        {/* Rule Number */}
        <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
          {index + 1}
        </div>

        {/* Rule Content */}
        <div className="flex-1 space-y-3">
          {/* Condition Expression */}
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-[var(--text-tertiary)]">Condition</Label>
            <ConditionExprField
              value={rule.condition}
              onChange={(val) => handleFieldChange('condition', val)}
              placeholder="state.get('score', 0) > 80"
              nodes={nodes}
              edges={edges}
              currentNodeId={currentNodeId}
              graphStateFields={graphStateFields}
            />
          </div>

          {/* Target Edge Selection */}
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-[var(--text-tertiary)]">Target Edge</Label>
            <Select
              value={
                rule.targetEdgeKey && rule.targetEdgeKey.trim() !== ''
                  ? rule.targetEdgeKey
                  : undefined
              }
              onValueChange={(routeKey) => {
                // Find matching edge by routeKey (which matches edgeOptions logic)
                const matchingEdge = edgeOptions.find((opt) => opt.routeKey === routeKey)
                if (matchingEdge) {
                  handleEdgeSelect(matchingEdge.edgeId)
                } else {
                  // Fallback: try to find by edgeId if routeKey is an edgeId
                  const edgeById = availableEdges.find((e) => e.id === routeKey)
                  if (edgeById) {
                    handleEdgeSelect(edgeById.id)
                  } else {
                    handleFieldChange('targetEdgeKey', routeKey)
                  }
                }
              }}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Select target edge" />
              </SelectTrigger>
              <SelectContent>
                {edgeOptions.length === 0 ? (
                  <div className="px-2 py-1.5 text-center text-xs text-[var(--text-muted)]">
                    No outgoing edges available
                  </div>
                ) : (
                  edgeOptions.map((option) => {
                    // Use routeKey (which is guaranteed to be non-empty from edgeOptions generation)
                    return (
                      <SelectItem key={option.edgeId} value={option.routeKey}>
                        {option.displayText}
                      </SelectItem>
                    )
                  })
                )}
              </SelectContent>
            </Select>
            {edgeOptions.length === 0 && (
              <div className="space-y-2">
                <p className="text-[9px] text-amber-600">
                  No edge found for this route. Create one?
                </p>
                {onCreateEdge && (
                  <div className="space-y-1.5">
                    <Select value={selectedTargetNodeId} onValueChange={setSelectedTargetNodeId}>
                      <SelectTrigger className="h-7 text-xs">
                        <SelectValue placeholder="Select target node" />
                      </SelectTrigger>
                      <SelectContent>
                        {nodes
                          .filter((n) => n.id !== currentNodeId)
                          .map((node) => (
                            <SelectItem key={node.id} value={node.id}>
                              {(node.data as { label?: string })?.label || node.id}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (selectedTargetNodeId && rule.targetEdgeKey) {
                          onCreateEdge(selectedTargetNodeId, rule.targetEdgeKey)
                          setSelectedTargetNodeId('')
                        }
                      }}
                      disabled={!selectedTargetNodeId || !rule.targetEdgeKey}
                      className="h-7 w-full text-xs"
                    >
                      <ArrowRight size={12} className="mr-1" />
                      Create Edge
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Show create edge option if route key doesn't match any edge */}
            {edgeOptions.length > 0 &&
              rule.targetEdgeKey &&
              !edgeOptions.find((opt) => opt.routeKey === rule.targetEdgeKey) &&
              onCreateEdge && (
                <div className="space-y-1.5 border-t border-[var(--border-muted)] pt-1">
                  <Label className="text-[9px] font-bold text-[var(--text-muted)]">Quick Create Edge</Label>
                  <Select value={selectedTargetNodeId} onValueChange={setSelectedTargetNodeId}>
                    <SelectTrigger className="h-7 text-xs">
                      <SelectValue placeholder="Select target node" />
                    </SelectTrigger>
                    <SelectContent>
                      {nodes
                        .filter((n) => n.id !== currentNodeId)
                        .map((node) => (
                          <SelectItem key={node.id} value={node.id}>
                            {(node.data as { label?: string })?.label || node.id}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (selectedTargetNodeId && rule.targetEdgeKey) {
                        onCreateEdge(selectedTargetNodeId, rule.targetEdgeKey)
                        setSelectedTargetNodeId('')
                      }
                    }}
                    disabled={!selectedTargetNodeId || !rule.targetEdgeKey}
                    className="h-7 w-full text-xs"
                  >
                    <ArrowRight size={12} className="mr-1" />
                    Create Edge with route_key: {rule.targetEdgeKey}
                  </Button>
                </div>
              )}
          </div>

          {/* Label */}
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-[var(--text-tertiary)]">Label</Label>
            <Input
              value={rule.label}
              onChange={(e) => handleFieldChange('label', e.target.value)}
              placeholder="e.g., High Score, Default"
              className="h-8 text-xs"
            />
          </div>

          {/* Validation Errors */}
          {hasErrors && (
            <div className="space-y-1">
              {validationErrors.map((error, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 rounded border border-red-200 bg-red-50 p-2 text-xs"
                >
                  <AlertCircle size={12} className="mt-0.5 flex-shrink-0 text-red-600" />
                  <div className="text-red-800">{error.message}</div>
                </div>
              ))}
            </div>
          )}

          {/* Validation Success */}
          {!hasErrors && rule.condition && rule.targetEdgeKey && (
            <div className="flex items-center gap-2 text-xs text-green-600">
              <CheckCircle2 size={12} />
              <span>Rule is valid</span>
            </div>
          )}
        </div>

        {/* Delete Button */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onDelete}
          className="h-7 w-7 flex-shrink-0 text-[var(--text-muted)] hover:text-[var(--status-error)]"
        >
          <Trash2 size={14} />
        </Button>
      </div>
    </div>
  )
}

/**
 * RouteListField - Manage routing rules with drag-and-drop sorting
 */
export function RouteListField({
  value,
  onChange,
  availableEdges,
  targetNodes,
  currentNodeId,
  nodes,
  edges,
  onCreateEdge,
  graphStateFields,
}: RouteListFieldProps) {
  const rules = Array.isArray(value) ? value : []

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event

    if (over && active.id !== over.id) {
      const oldIndex = rules.findIndex((r) => r.id === active.id)
      const newIndex = rules.findIndex((r) => r.id === over.id)

      const newRules = arrayMove(rules, oldIndex, newIndex).map((rule, index) => ({
        ...rule,
        priority: index,
      }))

      onChange(newRules)
    }
  }

  const handleAddRule = () => {
    const newRule: RouteRule = {
      id: generateUUID(),
      condition: '',
      targetEdgeKey: '',
      label: `Route ${rules.length + 1}`,
      priority: rules.length,
    }
    onChange([...rules, newRule])
  }

  const handleUpdateRule = (updatedRule: RouteRule) => {
    const newRules = rules.map((r) => (r.id === updatedRule.id ? updatedRule : r))
    onChange(newRules)
  }

  const handleDeleteRule = (ruleId: string) => {
    const newRules = rules
      .filter((r) => r.id !== ruleId)
      .map((rule, index) => ({
        ...rule,
        priority: index,
      }))
    onChange(newRules)
  }

  return (
    <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3">
      {rules.length === 0 && (
        <div className="py-4 text-center text-[10px] text-[var(--text-muted)]">
          No routing rules defined. Rules are evaluated in order (top to bottom).
        </div>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={rules.map((r) => r.id)} strategy={verticalListSortingStrategy}>
          <div className="space-y-2">
            {rules.map((rule, index) => (
              <RouteRuleItem
                key={rule.id}
                rule={rule}
                index={index}
                availableEdges={availableEdges}
                targetNodes={targetNodes}
                currentNodeId={currentNodeId}
                nodes={nodes}
                edges={edges}
                onUpdate={handleUpdateRule}
                onDelete={() => handleDeleteRule(rule.id)}
                onCreateEdge={onCreateEdge}
                graphStateFields={graphStateFields}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      <Button
        variant="outline"
        size="sm"
        onClick={handleAddRule}
        className="h-8 w-full border-dashed text-xs text-[var(--text-tertiary)]"
      >
        <Plus size={12} className="mr-1" />
        Add Route Rule
      </Button>

      {rules.length > 0 && (
        <p className="text-[9px] italic text-[var(--text-muted)]">
          Rules are evaluated from top to bottom. The first matching condition determines the route.
        </p>
      )}
    </div>
  )
}

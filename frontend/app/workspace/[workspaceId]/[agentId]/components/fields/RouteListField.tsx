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
import React, { useState, useMemo, useCallback } from 'react'
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
import { cn } from '@/lib/core/utils/cn'

import { validateRouteRuleEdgeMatch } from '../../services/edgeValidator'
import { RouteRule, EdgeData } from '../../types/graph'

import { ConditionExprField } from './ConditionExprField'

interface RouteListFieldProps {
  value: RouteRule[]
  onChange: (rules: RouteRule[]) => void
  availableEdges: Edge[]
  targetNodes: Node[]
  currentNodeId: string
  nodes: Node[]
  edges: Edge[]
  onCreateEdge?: (targetNodeId: string, routeKey: string) => void
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
}

const RouteRuleItem: React.FC<RouteRuleItemProps> = ({
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
}) => {
  const [showCreateEdge, setShowCreateEdge] = React.useState(false)
  const [selectedTargetNodeId, setSelectedTargetNodeId] = React.useState<string>('')
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: rule.id })

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
      const targetLabel = (targetNode?.data as { label?: string })?.label || targetNode?.id || edge.target
      // Ensure routeKey is never empty string - use edgeId as fallback
      const routeKey = (edgeData.route_key && edgeData.route_key.trim() !== '')
        ? edgeData.route_key
        : edge.id

      return {
        edgeId: edge.id,
        routeKey,
        label: edgeData.label || targetLabel,
        displayText: routeKey && routeKey !== edge.id ? `${routeKey} → ${targetLabel}` : targetLabel,
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
      const routeKey = (edgeData.route_key && edgeData.route_key.trim() !== '')
        ? edgeData.route_key
        : edgeId
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
        'border rounded-lg p-3 bg-white space-y-3',
        hasErrors && 'border-red-200 bg-red-50/30',
        isDragging && 'shadow-lg'
      )}
    >
      <div className="flex items-start gap-2">
        {/* Drag Handle */}
        <button
          {...attributes}
          {...listeners}
          className="mt-1 cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600"
        >
          <GripVertical size={16} />
        </button>

        {/* Rule Number */}
        <div className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-medium">
          {index + 1}
        </div>

        {/* Rule Content */}
        <div className="flex-1 space-y-3">
          {/* Condition Expression */}
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-gray-500">Condition</Label>
            <ConditionExprField
              value={rule.condition}
              onChange={(val) => handleFieldChange('condition', val)}
              placeholder="state.get('score', 0) > 80"
              nodes={nodes}
              edges={edges}
              currentNodeId={currentNodeId}
            />
          </div>

          {/* Target Edge Selection */}
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-gray-500">Target Edge</Label>
            <Select
              value={rule.targetEdgeKey && rule.targetEdgeKey.trim() !== '' ? rule.targetEdgeKey : undefined}
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
                  <div className="px-2 py-1.5 text-xs text-gray-400 text-center">
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
                    <Select
                      value={selectedTargetNodeId}
                      onValueChange={setSelectedTargetNodeId}
                    >
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
                          setShowCreateEdge(false)
                          setSelectedTargetNodeId('')
                        }
                      }}
                      disabled={!selectedTargetNodeId || !rule.targetEdgeKey}
                      className="w-full h-7 text-xs"
                    >
                      <ArrowRight size={12} className="mr-1" />
                      Create Edge
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Show create edge option if route key doesn't match any edge */}
            {edgeOptions.length > 0 && rule.targetEdgeKey && !edgeOptions.find((opt) => opt.routeKey === rule.targetEdgeKey) && onCreateEdge && (
              <div className="space-y-1.5 pt-1 border-t border-gray-100">
                <Label className="text-[9px] font-bold text-gray-400">Quick Create Edge</Label>
                <Select
                  value={selectedTargetNodeId}
                  onValueChange={setSelectedTargetNodeId}
                >
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
                  className="w-full h-7 text-xs"
                >
                  <ArrowRight size={12} className="mr-1" />
                  Create Edge with route_key: {rule.targetEdgeKey}
                </Button>
              </div>
            )}
          </div>

          {/* Label */}
          <div className="space-y-1.5">
            <Label className="text-[10px] font-bold text-gray-500">Label</Label>
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
                  className="flex items-start gap-2 p-2 bg-red-50 border border-red-200 rounded text-xs"
                >
                  <AlertCircle size={12} className="text-red-600 mt-0.5 flex-shrink-0" />
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
          className="h-7 w-7 text-gray-400 hover:text-red-500 flex-shrink-0"
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
export const RouteListField: React.FC<RouteListFieldProps> = ({
  value,
  onChange,
  availableEdges,
  targetNodes,
  currentNodeId,
  nodes,
  edges,
  onCreateEdge,
}) => {
  const rules = Array.isArray(value) ? value : []

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
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
      id: `route_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
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
    const newRules = rules.filter((r) => r.id !== ruleId).map((rule, index) => ({
      ...rule,
      priority: index,
    }))
    onChange(newRules)
  }

  return (
    <div className="space-y-3 border border-gray-200 rounded-xl p-3 bg-gray-50/30">
      {rules.length === 0 && (
        <div className="text-center py-4 text-[10px] text-gray-400">
          No routing rules defined. Rules are evaluated in order (top to bottom).
        </div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
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
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      <Button
        variant="outline"
        size="sm"
        onClick={handleAddRule}
        className="w-full border-dashed text-gray-500 h-8 text-xs"
      >
        <Plus size={12} className="mr-1" />
        Add Route Rule
      </Button>

      {rules.length > 0 && (
        <p className="text-[9px] text-gray-400 italic">
          Rules are evaluated from top to bottom. The first matching condition determines the route.
        </p>
      )}
    </div>
  )
}

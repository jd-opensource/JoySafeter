'use client'

import { Bot, Loader2, Zap, Layers, Copy, Trash2, PauseCircle, ArrowRight } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { memo, useState, useMemo } from 'react'
import { Handle, Position } from 'reactflow'

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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { useModels } from '@/hooks/queries/models'
import { useBuiltinTools } from '@/hooks/queries/tools'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { cn } from '@/lib/core/utils/cn'
import { nodeRegistry, type FieldSchema } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/executionStore'

import { useTranslation } from '@/lib/i18n'

interface BuilderNodeProps {
  id: string
  data: {
    type: string
    label?: string
    config?: Record<string, unknown>
  }
  selected?: boolean
}

const BuilderNode = ({ id, data, selected }: BuilderNodeProps) => {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)
  const activeExecutionNodeId = useBuilderStore((state) => state.activeExecutionNodeId)
  const deleteNode = useBuilderStore((state) => state.deleteNode)
  const duplicateNode = useBuilderStore((state) => state.duplicateNode)
  const highlightedStateVariable = useBuilderStore((state) => state.highlightedStateVariable)
  const setHighlightedStateVariable = useBuilderStore((state) => state.setHighlightedStateVariable)
  const isExecuting = activeExecutionNodeId === id

  const executionSteps = useExecutionStore((state) => state.steps)
  const nodeExecutionStatus = useMemo(() => {
    // Find the latest node_lifecycle step for this node
    const nodeSteps = executionSteps.filter(s => s.nodeId === id && s.stepType === 'node_lifecycle')
    if (nodeSteps.length === 0) return null
    return nodeSteps[nodeSteps.length - 1].status
  }, [executionSteps, id])

  const pendingInterrupts = useExecutionStore((state) => state.pendingInterrupts)
  const isInterrupted = pendingInterrupts.has(id)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Check if node has tools configuration (needed for display)
  const hasTools = useMemo(() => {
    const tools = data.config?.tools
    return !!(tools && typeof tools === 'object' &&
      (Array.isArray((tools as any).builtin) || Array.isArray((tools as any).mcp)))
  }, [data.config?.tools])

  // Check if node has model configuration (needed for display)
  const hasModel = useMemo(() => {
    return !!data.config?.model || !!data.config?.model_name
  }, [data.config?.model, data.config?.model_name])

  // Conditionally enable queries: only when node has config or is selected (for property panel)
  // This avoids unnecessary requests when page loads
  const { data: models = [] } = useModels({ enabled: hasModel || selected })
  const { data: builtinToolsData = [] } = useBuiltinTools({ enabled: hasTools || selected })
  const builtinTools = useMemo(() =>
    builtinToolsData.map(t => ({ id: t.id, label: t.label })),
    [builtinToolsData]
  )

  // Fetch definition from registry
  const def = nodeRegistry.get(data.type)

  // Get translated labels
  const getNodeLabel = (type: string) => {
    const key = `workspace.nodeTypes.${type}`
    try {
      const translated = t(key)
      if (translated && translated !== key) {
        return translated
      }
    } catch {
      // Translation key doesn't exist, use default
    }
    return def?.label || 'Unknown Node'
  }

  const getNodeSubLabel = (type: string) => {
    const key = `workspace.nodeTypes.${type}SubLabel`
    try {
      const translated = t(key)
      if (translated && translated !== key) {
        return translated
      }
    } catch {
      // Translation key doesn't exist, use default
    }
    return def?.subLabel || type
  }

  // Fallback defaults if type not found
  const Icon = def?.icon || Bot
  const colorClass = def?.style.color || 'text-gray-500'
  const bgClass = def?.style.bg || 'bg-gray-50'
  const title = data.label || getNodeLabel(data.type)
  const subLabel = getNodeSubLabel(data.type)
  const useDeepAgents = data.config?.useDeepAgents === true

  // Format display value based on field type
  const getDisplayValue = (field: FieldSchema, value: unknown): string => {
    if (value == null || value === '') return '-'

    switch (field.type) {
      case 'modelSelect':
        // Try to get model label from the models list
        if (typeof value === 'string') {
          // Support both new format (provider:name) and old format (name only)
          let model = models.find(m => m.id === value)

          // Backward compatibility: if not found with new format, try old format (name only)
          if (!model && !value.includes(':')) {
            // Try to find by name only (old format)
            model = models.find(m => {
              if (!m.id) return false
              const modelName = m.id.includes(':') ? m.id.split(':')[1] : m.id
              return modelName === value
            })
          }

          if (model) return model.label
          // Fallback: format model ID to readable name
          // Extract model name if in new format (provider:name)
          const modelName = value.includes(':') ? value.split(':')[1] : value
          const parts = modelName.split('-').filter(p => !['preview'].includes(p))
          return parts
            .map(part => part.charAt(0).toUpperCase() + part.slice(1))
            .join(' ')
        }
        return String(value)

      case 'toolSelector':
        if (typeof value === 'object' && value !== null) {
          const toolsValue = value as { builtin?: string[]; mcp?: string[] }
          const builtinIds = toolsValue.builtin || []
          const mcpIds = toolsValue.mcp || []
          const total = builtinIds.length + mcpIds.length
          if (total === 0) return '-'

          // Get tool labels
          const builtinLabels = builtinIds
            .map(id => builtinTools.find(t => t.id === id)?.label || id)
            .filter(Boolean)

          // Parse MCP tool IDs: format is "server_name::tool_name"
          // Extract tool name part for display
          const mcpLabels = mcpIds.map(id => {
            const parts = id.split('::')
            return parts.length === 2 ? parts[1] : id
          })

          if (total === 1) {
            return builtinLabels[0] || mcpLabels[0] || '-'
          }
          if (total === 2 && builtinLabels.length > 0) {
            return builtinLabels.length === 2
              ? `${builtinLabels[0]}, ${builtinLabels[1]}`
              : `${builtinLabels[0]}, ${mcpLabels[0] || ''}`
          }
          return t('workspace.toolsCount', { count: total })
        }
        return '-'

      case 'select':
        return String(value)

      case 'boolean':
        return value === true ? t('workspace.enabled') : t('workspace.disabled')

      case 'text':
      case 'textarea':
        const textValue = String(value)
        return textValue.length > 30 ? `${textValue.slice(0, 30)}...` : textValue

      case 'number':
        return String(value)

      default:
        return String(value)
    }
  }

  // Get field label with translation
  const getFieldLabel = (field: FieldSchema): string => {
    const fieldKey = `workspace.nodeFields.${field.key}`
    try {
      const translated = t(fieldKey)
      if (translated && translated !== fieldKey) {
        return translated
      }
    } catch {
      // Translation key doesn't exist, use default
    }
    return field.label
  }

  // Calculate state reads/writes (static + dynamic)
  const stateUsage = useMemo(() => {
    // ... (existing code)
    const reads = new Set(def?.stateReads || [])
    const writes = new Set(def?.stateWrites || [])

    // Dynamic: Input Mapping (Reads)
    if (data.config?.input_mapping) {
      const mapping = data.config.input_mapping as any
      if (Array.isArray(mapping)) {
        mapping.forEach(m => {
          if (typeof m.value === 'string' && m.value.startsWith('state.get(')) {
            const match = m.value.match(/state\.get\(['"](.+)['"]\)/)
            if (match) reads.add(match[1])
          }
        })
      }
    }

    // Dynamic: Output Mapping (Writes)
    if (data.config?.output_map) {
      const mapping = data.config.output_map as Record<string, string>
      Object.values(mapping).forEach(val => writes.add(val))
    }

    // Dynamic: Aggregator Source Variables (Reads)
    if (data.config?.source_variables) {
      const sources = data.config.source_variables
      if (Array.isArray(sources)) {
        sources.forEach((s: any) => typeof s === 'string' && reads.add(s))
      } else if (typeof sources === 'string') {
        // handle comma separated string
        (sources as string).split(',').map(s => s.trim()).filter(Boolean).forEach(s => reads.add(s))
      }
    }

    // Dynamic: Aggregator Target Variable (Writes)
    if (data.config?.target_variable && typeof data.config.target_variable === 'string') {
      writes.add(data.config.target_variable)
    }

    return {
      reads: Array.from(reads),
      writes: Array.from(writes)
    }
  }, [def, data.config])

  const isReadingHighlighted = highlightedStateVariable && stateUsage.reads.includes(highlightedStateVariable)
  const isWritingHighlighted = highlightedStateVariable && stateUsage.writes.includes(highlightedStateVariable)

  // Get important properties to display on node
  const displayProperties = useMemo(() => {
    if (!def?.schema || !data.config) return []

    // Filter important fields to display
    const importantFields = def.schema.filter((field) => {
      // Skip fields that shouldn't be displayed
      if (['systemPrompt', 'template', 'expression', 'memoryPrompt', 'description'].includes(field.key)) {
        return false
      }
      // Only show fields that have values
      const value = data.config?.[field.key]
      return value !== undefined && value !== null && value !== ''
    })

    // Prioritize: model, tools, then others
    const sortedFields = importantFields.sort((a, b) => {
      const priority = { model: 1, tools: 2 }
      const aPriority = priority[a.key as keyof typeof priority] || 3
      const bPriority = priority[b.key as keyof typeof priority] || 3
      return aPriority - bPriority
    })

    // Limit to 3 most important properties
    return sortedFields.slice(0, 3).map((field) => {
      const value = data.config?.[field.key]
      return {
        label: getFieldLabel(field),
        value: getDisplayValue(field, value),
        key: field.key,
      }
    })
  }, [def?.schema, data.config, t, models, builtinTools])

  return (
    <div
      className={cn(
        'group min-w-[140px] rounded-xl border bg-white/95 backdrop-blur-sm shadow-sm transition-all duration-500 relative',
        selected
          ? 'border-blue-500 ring-2 ring-blue-500/10'
          : 'border-gray-200 hover:border-gray-300',
        isExecuting && 'border-transparent shadow-[0_0_25px_rgba(59,130,246,0.4)] scale-105 z-50',
        isInterrupted && 'border-amber-400 ring-2 ring-amber-400/20 shadow-[0_0_15px_rgba(251,191,36,0.3)] z-40',
        // State Highlighting
        isReadingHighlighted && !isWritingHighlighted && 'border-blue-400 ring-2 ring-blue-400/30 shadow-[0_0_15px_rgba(96,165,250,0.3)] z-30',
        isWritingHighlighted && !isReadingHighlighted && 'border-amber-400 ring-2 ring-amber-400/30 shadow-[0_0_15px_rgba(251,191,36,0.3)] z-30',
        isReadingHighlighted && isWritingHighlighted && 'border-purple-400 ring-2 ring-purple-400/30 shadow-[0_0_15px_rgba(168,85,247,0.3)] z-30',
        // Execution Status
        nodeExecutionStatus === 'success' && !isExecuting && !selected && 'border-green-500 shadow-[0_0_10px_rgba(34,197,94,0.2)]',
        nodeExecutionStatus === 'error' && !isExecuting && !selected && 'border-red-500 shadow-[0_0_10px_rgba(239,68,68,0.2)]'
      )}
    >
      {/* Quick Actions - Show on hover */}
      <div
        className={cn(
          '-top-[46px] absolute right-0',
          'flex flex-row items-center',
          'opacity-0 transition-opacity duration-200 group-hover:opacity-100',
          'gap-[5px] rounded-[10px] bg-white border border-gray-200 shadow-sm p-[5px]',
          'pointer-events-auto z-10'
        )}
      >
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  if (!userPermissions.canEdit) {
                    toast({
                      title: t('workspace.noPermission'),
                      description: t('workspace.cannotCopyNode'),
                      variant: 'destructive',
                    })
                    return
                  }
                  duplicateNode(id)
                }}
                className={`h-[23px] w-[23px] rounded-[8px] bg-transparent p-0 transition-colors flex items-center justify-center ${userPermissions.canEdit
                  ? 'text-gray-500 hover:bg-gray-100 hover:text-gray-900'
                  : 'text-gray-300 cursor-not-allowed opacity-50'
                  }`}
              >
                <Copy className="h-[11px] w-[11px]" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('workspace.duplicate')}</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Context Badge for '*' reads */}
        {stateUsage.reads.includes('*') && (
          <div className="text-[6px] px-1 py-0.5 rounded bg-gray-50 text-gray-500 border border-gray-100 italic" title="Reads All State">
            reads: *
          </div>
        )}

        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  if (!userPermissions.canEdit) {
                    toast({
                      title: t('workspace.noPermission'),
                      description: t('workspace.cannotDeleteNode'),
                      variant: 'destructive',
                    })
                    return
                  }
                  setShowDeleteConfirm(true)
                }}
                className={`h-[23px] w-[23px] rounded-[8px] bg-transparent p-0 transition-colors flex items-center justify-center ${userPermissions.canEdit
                  ? 'text-red-500 hover:bg-red-50 hover:text-red-600'
                  : 'text-gray-300 cursor-not-allowed opacity-50'
                  }`}
              >
                <Trash2 className="h-[11px] w-[11px]" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('workspace.delete')}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* Dynamic Animated Border for Execution */}
      {isExecuting && (
        <div className="absolute -inset-[2px] rounded-xl overflow-hidden pointer-events-none z-0">
          <div className="absolute inset-[-200%] bg-[conic-gradient(from_0deg,transparent_20%,#3b82f6_50%,transparent_80%)] animate-[spin_3s_linear_infinite]" />
          <div className="absolute inset-[2px] bg-white rounded-[10px]" />
        </div>
      )}

      {/* Internal Content Container */}
      <div className="relative z-10 p-3">
        {/* Execution Status Badge */}
        {isExecuting && (
          <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-blue-600 text-[8px] font-bold text-white px-2 py-0.5 rounded-full shadow-lg flex items-center gap-1 animate-pulse border border-white">
            <Zap size={8} className="fill-current" />
            {t('workspace.running')}
          </div>
        )}
        {isInterrupted && (
          <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-amber-500 text-[8px] font-bold text-white px-2 py-0.5 rounded-full shadow-lg flex items-center gap-1 animate-pulse border border-white">
            <PauseCircle className="h-2.5 w-2.5" />
            {t('workspace.waiting', { defaultValue: 'Waiting' })}
          </div>
        )}

        <div className="flex items-center gap-2.5 mb-2">
          <div
            className={cn(
              'p-1.5 rounded-lg shrink-0 border border-black/5 transition-colors duration-300',
              isExecuting ? 'bg-blue-600 text-white' : bgClass + ' ' + colorClass
            )}
          >
            <Icon size={14} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <div className="text-[10px] font-bold text-gray-900 leading-tight truncate flex-1 min-w-0">
                {title}
              </div>
              {useDeepAgents && (
                <div className="shrink-0 flex items-center gap-0.5" title="DeepAgents Mode">
                  <Layers size={10} className="text-purple-600" />
                </div>
              )}
            </div>
            <div className="text-[7px] text-gray-400 uppercase tracking-widest font-bold leading-none mt-0.5">
              {subLabel}
            </div>
          </div>
        </div>

        {/* Property Display */}
        {displayProperties.length > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-100/50 space-y-1">
            {displayProperties.map((prop) => (
              <div key={prop.key} className="flex items-center gap-[8px]">
                <span
                  className="min-w-0 truncate text-[7px] text-gray-400 capitalize leading-tight"
                  title={prop.label}
                >
                  {prop.label}
                </span>
                <span
                  className="flex-1 truncate text-right text-[7px] text-gray-600 font-medium leading-tight"
                  title={prop.value}
                >
                  {prop.value}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Route Indicator - Show goto information */}
        {(() => {
          const config = data.config || {}
          const goto = config.goto || config.trueGoto || config.falseGoto ||
            (config.rules && Array.isArray(config.rules) && config.rules.length > 0
              ? config.rules.find((r: any) => r.commandGoto)?.commandGoto
              : null) ||
            config.commandDefaultGoto
          const routeDecisions = useExecutionStore.getState().routeDecisions
          const latestDecision = routeDecisions
            .filter(d => d.nodeId === id)
            .sort((a, b) => b.timestamp - a.timestamp)[0]
          const actualGoto = latestDecision?.decision.goto || goto

          if (!actualGoto) return null

          return (
            <div className="mt-2 pt-2 border-t border-gray-100/50">
              <div className="flex items-center gap-1 text-[7px] text-blue-600">
                <ArrowRight size={8} className="text-blue-500" />
                <span className="font-mono font-semibold truncate" title={actualGoto}>
                  → {actualGoto}
                </span>
              </div>
            </div>
          )
        })()}

        {/* State Dependencies (Reads/Writes) */}
        {(stateUsage.reads.length > 0 || stateUsage.writes.length > 0) && (
          <div className="mt-2 pt-2 border-t border-gray-100/50 flex flex-col gap-1.5">
            {/* Reads */}
            {stateUsage.reads.length > 0 && stateUsage.reads.some(r => r !== '*') && (
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-[7px] text-gray-400 font-medium">Reads:</span>
                {stateUsage.reads.filter(r => r !== '*').map((read) => (
                  <div
                    key={`read-${read}`}
                    className="text-[6.5px] px-1 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-100 flex items-center gap-0.5 cursor-pointer hover:bg-blue-100 transition-colors"
                    title={`Highlight nodes reading or writing '${read}'`}
                    onMouseEnter={() => setHighlightedStateVariable(read)}
                    onMouseLeave={() => setHighlightedStateVariable(null)}
                  >
                    {read}
                  </div>
                ))}
              </div>
            )}
            {/* Writes */}
            {stateUsage.writes.length > 0 && stateUsage.writes.some(w => w !== '*') && (
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-[7px] text-gray-400 font-medium">Writes:</span>
                {stateUsage.writes.filter(w => w !== '*').map((write) => (
                  <div
                    key={`write-${write}`}
                    className="text-[6.5px] px-1 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-100 flex items-center gap-0.5 cursor-pointer hover:bg-amber-100 transition-colors"
                    title={`Highlight nodes reading or writing '${write}'`}
                    onMouseEnter={() => setHighlightedStateVariable(write)}
                    onMouseLeave={() => setHighlightedStateVariable(null)}
                  >
                    {write}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {isExecuting && (
          <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-gray-100/50">
            <Loader2 size={8} className="text-blue-500 animate-spin" />
            <span className="text-[7px] text-blue-500 font-bold animate-pulse">
              {t('workspace.synchronizing')}
            </span>
          </div>
        )}
      </div>

      {/* Connection Handles - Must be direct children of node container, like the working version */}
      <Handle type="target" position={Position.Left} className="!bg-blue-400 !w-2 !h-2 !-left-[5px] border-2 border-white shadow-sm" />
      <Handle type="source" position={Position.Right} className="!bg-blue-400 !w-2 !h-2 !-right-[5px] border-2 border-white shadow-sm" />

      {/* Delete Node Confirmation Dialog - Uses Portal so won't affect node layout */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.deleteNode')}</AlertDialogTitle>
            <AlertDialogDescription>
              {title ? (
                <>
                  {t('workspace.deleteNodeConfirmMessagePrefix')}{' '}
                  <span className="font-semibold text-[#ef4444]">{title}</span>
                  {t('workspace.deleteNodeConfirmMessageSuffix')}
                </>
              ) : (
                t('workspace.deleteNodeConfirmMessageDefault')
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setShowDeleteConfirm(false)}>
              {t('workspace.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!userPermissions.canEdit) {
                  toast({
                    title: t('workspace.noPermission'),
                    description: t('workspace.cannotDeleteNode'),
                    variant: 'destructive',
                  })
                  setShowDeleteConfirm(false)
                  return
                }
                deleteNode(id)
                setShowDeleteConfirm(false)
              }}
              className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
            >
              {t('workspace.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export default memo(BuilderNode)

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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { useModels } from '@/hooks/queries/models'
import { useBuiltinTools } from '@/hooks/queries/tools'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { nodeRegistry, type FieldSchema } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/executionStore'


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
  const isExecuting = activeExecutionNodeId === id

  const executionSteps = useExecutionStore((state) => state.steps)
  const nodeExecutionStatus = useMemo(() => {
    // Find the latest node_lifecycle step for this node
    const nodeSteps = executionSteps.filter(
      (s) => s.nodeId === id && s.stepType === 'node_lifecycle',
    )
    if (nodeSteps.length === 0) return null
    return nodeSteps[nodeSteps.length - 1].status
  }, [executionSteps, id])

  const pendingInterrupts = useExecutionStore((state) => state.pendingInterrupts)
  const isInterrupted = pendingInterrupts.has(id)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // Check if node has tools configuration (needed for display)
  const hasTools = useMemo(() => {
    const tools = data.config?.tools
    return !!(
      tools &&
      typeof tools === 'object' &&
      (Array.isArray((tools as any).builtin) || Array.isArray((tools as any).mcp))
    )
  }, [data.config?.tools])

  // Check if node has model configuration (needed for display)
  const hasModel = useMemo(() => {
    return !!data.config?.model || !!data.config?.model_name
  }, [data.config?.model, data.config?.model_name])

  // Conditionally enable queries: only when node has config or is selected (for property panel)
  // This avoids unnecessary requests when page loads
  const { data: models = [] } = useModels({ enabled: hasModel || selected })
  const { data: builtinToolsData = [] } = useBuiltinTools({ enabled: hasTools || selected })
  const builtinTools = useMemo(
    () => builtinToolsData.map((t) => ({ id: t.id, label: t.label })),
    [builtinToolsData],
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
  const colorClass = def?.style.color || 'text-[var(--text-tertiary)]'
  const bgClass = def?.style.bg || 'bg-[var(--surface-1)]'
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
          let model = models.find((m) => m.id === value)

          // Backward compatibility: if not found with new format, try old format (name only)
          if (!model && !value.includes(':')) {
            // Try to find by name only (old format)
            model = models.find((m) => {
              if (!m.id) return false
              const modelName = m.id.includes(':') ? m.id.split(':')[1] : m.id
              return modelName === value
            })
          }

          if (model) return model.label
          // Fallback: format model ID to readable name
          // Extract model name if in new format (provider:name)
          const modelName = value.includes(':') ? value.split(':')[1] : value
          const parts = modelName.split('-').filter((p) => !['preview'].includes(p))
          return parts.map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
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
            .map((id) => builtinTools.find((t) => t.id === id)?.label || id)
            .filter(Boolean)

          // Parse MCP tool IDs: format is "server_name::tool_name"
          // Extract tool name part for display
          const mcpLabels = mcpIds.map((id) => {
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

  // Get important properties to display on node
  const displayProperties = useMemo(() => {
    if (!def?.schema || !data.config) return []

    // Filter important fields to display
    const importantFields = def.schema.filter((field) => {
      // Skip fields that shouldn't be displayed
      if (
        ['systemPrompt', 'memoryPrompt', 'description', 'useDeepAgents', 'enableMemory', 'skills'].includes(
          field.key,
        )
      ) {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def?.schema, data.config, t, models, builtinTools])

  return (
    <div
      className={cn(
        'group relative min-w-[140px] rounded-xl border bg-[var(--surface-elevated)] shadow-sm backdrop-blur-sm transition-all duration-500',
        selected
          ? 'border-primary ring-2 ring-primary/10'
          : 'border-[var(--border)] hover:border-[var(--border-strong)]',
        isExecuting && 'z-50 scale-105 border-transparent shadow-[0_0_25px_rgba(59,130,246,0.4)]',
        isInterrupted &&
          'z-40 border-[var(--status-warning)] shadow-[0_0_15px_rgba(251,191,36,0.3)] ring-2 ring-amber-400/20',
        // Execution Status
        nodeExecutionStatus === 'success' &&
          !isExecuting &&
          !selected &&
          'border-[var(--status-success)] shadow-[0_0_10px_rgba(34,197,94,0.2)]',
        nodeExecutionStatus === 'error' &&
          !isExecuting &&
          !selected &&
          'border-[var(--status-error)] shadow-[0_0_10px_rgba(239,68,68,0.2)]',
      )}
    >
      {/* Quick Actions - Show on hover */}
      <div
        className={cn(
          'absolute -top-[46px] right-0',
          'flex flex-row items-center',
          'opacity-0 transition-opacity duration-200 group-hover:opacity-100',
          'gap-[5px] rounded-[10px] border border-[var(--border)] bg-[var(--surface-elevated)] p-[5px] shadow-sm',
          'pointer-events-auto z-10',
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
                className={`flex h-[23px] w-[23px] items-center justify-center rounded-[8px] bg-transparent p-0 transition-colors ${
                  userPermissions.canEdit
                    ? 'text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]'
                    : 'cursor-not-allowed text-[var(--text-disabled)] opacity-50'
                }`}
              >
                <Copy className="h-[11px] w-[11px]" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('workspace.duplicate')}</TooltipContent>
          </Tooltip>
        </TooltipProvider>

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
                className={`flex h-[23px] w-[23px] items-center justify-center rounded-[8px] bg-transparent p-0 transition-colors ${
                  userPermissions.canEdit
                    ? 'text-[var(--status-error)] hover:bg-[var(--status-error-bg)] hover:text-[var(--status-error-hover)]'
                    : 'cursor-not-allowed text-[var(--text-disabled)] opacity-50'
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
        <div className="pointer-events-none absolute -inset-[2px] z-0 overflow-hidden rounded-xl">
          <div className="absolute inset-[-200%] animate-[spin_3s_linear_infinite] bg-[conic-gradient(from_0deg,transparent_20%,#3b82f6_50%,transparent_80%)]" />
          <div className="absolute inset-[2px] rounded-[10px] bg-[var(--surface-elevated)]" />
        </div>
      )}

      {/* Internal Content Container */}
      <div className="relative z-10 p-3">
        {/* Execution Status Badge */}
        {isExecuting && (
          <div className="absolute -top-2.5 left-1/2 flex -translate-x-1/2 animate-pulse items-center gap-1 rounded-full border border-white bg-[var(--brand-600)] px-2 py-0.5 text-[8px] font-bold text-white shadow-lg">
            <Zap size={8} className="fill-current" />
            {t('workspace.running')}
          </div>
        )}
        {isInterrupted && (
          <div className="absolute -top-2.5 left-1/2 flex -translate-x-1/2 animate-pulse items-center gap-1 rounded-full border border-white bg-[var(--status-warning)] px-2 py-0.5 text-[8px] font-bold text-white shadow-lg">
            <PauseCircle className="h-2.5 w-2.5" />
            {t('workspace.waiting', { defaultValue: 'Waiting' })}
          </div>
        )}

        <div className="mb-2 flex items-center gap-2.5">
          <div
            className={cn(
              'shrink-0 rounded-lg border border-black/5 p-1.5 transition-colors duration-300',
              isExecuting ? 'bg-[var(--brand-600)] text-white' : bgClass + ' ' + colorClass,
            )}
          >
            <Icon size={14} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-1.5">
              <div className="min-w-0 flex-1 truncate text-[10px] font-bold leading-tight text-[var(--text-primary)]">
                {title}
              </div>
              {useDeepAgents && (
                <div className="flex shrink-0 items-center gap-0.5" title="DeepAgents Mode">
                  <Layers size={10} className="text-purple-600" />
                </div>
              )}
            </div>
            <div className="mt-0.5 text-[7px] font-bold uppercase leading-none tracking-widest text-[var(--text-muted)]">
              {subLabel}
            </div>
          </div>
        </div>

        {/* Property Display */}
        {displayProperties.length > 0 && (
          <div className="mt-2 space-y-1 border-t border-[var(--divider)] pt-2">
            {displayProperties.map((prop) => (
              <div key={prop.key} className="flex items-center gap-[8px]">
                <span
                  className="min-w-0 truncate text-[7px] capitalize leading-tight text-[var(--text-muted)]"
                  title={prop.label}
                >
                  {prop.label}
                </span>
                <span
                  className="flex-1 truncate text-right text-[7px] font-medium leading-tight text-[var(--text-secondary)]"
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
          const goto =
            config.goto ||
            config.trueGoto ||
            config.falseGoto ||
            (config.rules && Array.isArray(config.rules) && config.rules.length > 0
              ? config.rules.find((r: any) => r.commandGoto)?.commandGoto
              : null) ||
            config.commandDefaultGoto
          const routeDecisions = useExecutionStore.getState().routeDecisions
          const latestDecision = routeDecisions
            .filter((d) => d.nodeId === id)
            .sort((a, b) => b.timestamp - a.timestamp)[0]
          const actualGoto = latestDecision?.decision.goto || goto

          if (!actualGoto) return null

          return (
            <div className="mt-2 border-t border-[var(--divider)] pt-2">
              <div className="flex items-center gap-1 text-[7px] text-primary">
                <ArrowRight size={8} className="text-primary" />
                <span className="truncate font-mono font-semibold" title={actualGoto}>
                  → {actualGoto}
                </span>
              </div>
            </div>
          )
        })()}

        {isExecuting && (
          <div className="mt-2 flex items-center gap-1.5 border-t border-[var(--divider)] pt-2">
            <Loader2 size={8} className="animate-spin text-primary" />
            <span className="animate-pulse text-[7px] font-bold text-primary">
              {t('workspace.synchronizing')}
            </span>
          </div>
        )}
      </div>

      {/* Connection Handles - Must be direct children of node container, like the working version */}
      <Handle
        type="target"
        position={Position.Left}
        className="!-left-[5px] !h-2 !w-2 border-2 border-white !bg-[var(--brand-400)] shadow-sm"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!-right-[5px] !h-2 !w-2 border-2 border-white !bg-[var(--brand-400)] shadow-sm"
      />

      {/* Delete Node Confirmation Dialog - Uses Portal so won't affect node layout */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.deleteNode')}</AlertDialogTitle>
            <AlertDialogDescription>
              {title ? (
                <>
                  {t('workspace.deleteNodeConfirmMessagePrefix')}{' '}
                  <span className="font-semibold text-[var(--status-error)]">{title}</span>
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
              className="bg-destructive text-white hover:bg-destructive/90"
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

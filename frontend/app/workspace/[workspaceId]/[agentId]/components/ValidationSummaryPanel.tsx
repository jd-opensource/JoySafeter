'use client'

import { X, AlertCircle, CheckCircle2, ArrowRight, FileX, GitBranch, Network } from 'lucide-react'
import { useMemo } from 'react'
import { Node, Edge } from 'reactflow'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useBuilderStore } from '../stores/builderStore'

interface ValidationSummaryPanelProps {
  nodes: Node[]
  edges: Edge[]
  onClose: () => void
  onSelectNode?: (nodeId: string) => void
  onSelectEdge?: (edgeId: string) => void
}

/**
 * ValidationSummaryPanel - Display all validation errors in the graph
 */
export function ValidationSummaryPanel({
  nodes,
  edges: _edges,
  onClose,
  onSelectNode,
  onSelectEdge,
}: ValidationSummaryPanelProps) {
  const { t } = useTranslation()
  const { validationErrors } = useBuilderStore()

  const allErrors = useMemo(() => validationErrors || [], [validationErrors])

  // Helper to translate category names
  const translateCategory = (category: string): string => {
    switch (category) {
      case 'Graph Structure':
        return t('workspace.graphStructure')
      case 'Node Configuration':
        return t('workspace.nodeConfiguration')
      case 'DeepAgents Structure':
        return t('workspace.deepAgentsStructure')
      default:
        return category
    }
  }

  // Group errors by category
  const errorsByCategory = useMemo(() => {
    const grouped: Record<string, typeof allErrors> = {}
    allErrors.forEach((error) => {
      const category = error.category || 'Other'
      if (!grouped[category]) {
        grouped[category] = []
      }
      grouped[category].push(error)
    })
    return grouped
  }, [allErrors])

  const criticalErrors = allErrors.filter((e) => e.severity === 'error')
  const warnings = allErrors.filter((e) => e.severity === 'warning')
  const hasErrors = criticalErrors.length > 0
  const hasWarnings = warnings.length > 0

  const handleErrorClick = (error: (typeof allErrors)[0]) => {
    if (error.nodeId && onSelectNode) {
      onSelectNode(error.nodeId)
      onClose()
    } else if (error.edgeId && onSelectEdge) {
      onSelectEdge(error.edgeId)
      onClose()
    }
  }

  return (
    <div className="absolute right-4 top-4 z-50 flex max-h-[calc(100vh-120px)] w-[360px] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl duration-300 animate-in fade-in slide-in-from-right-10">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-gray-100 bg-white px-3 py-2.5">
        <div className="flex items-center gap-2.5 overflow-hidden text-gray-900">
          <div
            className={cn(
              'shrink-0 rounded-md border border-gray-100 p-1 shadow-sm',
              hasErrors
                ? 'bg-red-50 text-red-600'
                : hasWarnings
                  ? 'bg-amber-50 text-amber-600'
                  : 'bg-green-50 text-green-600',
            )}
          >
            {hasErrors ? (
              <AlertCircle size={12} />
            ) : hasWarnings ? (
              <AlertCircle size={12} />
            ) : (
              <CheckCircle2 size={12} />
            )}
          </div>
          <div className="flex min-w-0 flex-col">
            <h3 className="truncate text-sm font-bold leading-tight">
              {t('workspace.validationSummary')}
            </h3>
            <span className="text-[9px] font-bold uppercase tracking-widest text-gray-400">
              {allErrors.length}{' '}
              {allErrors.length !== 1 ? t('workspace.issues') : t('workspace.issue')}
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-6 w-6 shrink-0 text-gray-300 hover:bg-gray-100 hover:text-gray-600"
        >
          <X size={14} />
        </Button>
      </div>

      {/* Body */}
      <div className="custom-scrollbar flex-1 space-y-3 overflow-y-auto p-3">
        {/* Summary Stats */}
        <div className="grid grid-cols-3 gap-1">
          <div
            className={cn(
              'rounded-md border px-1.5 py-1 text-center',
              hasErrors ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-gray-50',
            )}
          >
            <div className="text-sm font-bold leading-tight text-red-600">
              {criticalErrors.length}
            </div>
            <div className="mt-0.5 text-[9px] uppercase leading-tight text-gray-600">
              {t('workspace.errors')}
            </div>
          </div>
          <div
            className={cn(
              'rounded-md border px-1.5 py-1 text-center',
              hasWarnings ? 'border-amber-200 bg-amber-50' : 'border-gray-200 bg-gray-50',
            )}
          >
            <div className="text-sm font-bold leading-tight text-amber-600">{warnings.length}</div>
            <div className="mt-0.5 text-[9px] uppercase leading-tight text-gray-600">
              {t('workspace.warnings')}
            </div>
          </div>
          <div
            className={cn(
              'rounded-md border px-1.5 py-1 text-center',
              allErrors.length === 0
                ? 'border-green-200 bg-green-50'
                : 'border-gray-200 bg-gray-50',
            )}
          >
            <div className="text-sm font-bold leading-tight text-green-600">{nodes.length}</div>
            <div className="mt-0.5 text-[9px] uppercase leading-tight text-gray-600">
              {t('workspace.nodes')}
            </div>
          </div>
        </div>

        {/* Success State */}
        {allErrors.length === 0 && (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <CheckCircle2 size={36} className="mb-2 text-green-500" />
            <h4 className="mb-1 text-sm font-semibold text-gray-900">
              {t('workspace.allValidationsPassed')}
            </h4>
            <p className="text-xs text-gray-500">{t('workspace.graphReadyToDeploy')}</p>
          </div>
        )}

        {/* Errors by Category */}
        {Object.entries(errorsByCategory).map(([category, categoryErrors]) => (
          <div key={category} className="space-y-1.5">
            <Label className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-400">
              {category === 'Graph Structure' && <FileX size={11} />}
              {category === 'Node Configuration' && <GitBranch size={11} />}
              {category === 'Edge Configuration' && <ArrowRight size={11} />}
              {category === 'DeepAgents Structure' && <Network size={11} />}
              {translateCategory(category)} ({categoryErrors.length})
            </Label>
            <div className="space-y-1">
              {categoryErrors.map((error, idx) => {
                const node = error.nodeId ? nodes.find((n) => n.id === error.nodeId) : null
                const nodeLabel = node ? (node.data as { label?: string })?.label || node.id : null
                const isClickable = (error.nodeId && onSelectNode) || (error.edgeId && onSelectEdge)

                return (
                  <div
                    key={idx}
                    onClick={() => isClickable && handleErrorClick(error)}
                    className={cn(
                      'flex items-start gap-1.5 rounded-lg border p-2 text-xs transition-colors',
                      error.severity === 'error'
                        ? 'border-red-200 bg-red-50'
                        : error.severity === 'warning'
                          ? 'border-amber-200 bg-amber-50'
                          : 'border-blue-200 bg-blue-50',
                      isClickable && 'cursor-pointer hover:shadow-sm',
                    )}
                  >
                    <AlertCircle
                      size={12}
                      className={cn(
                        'mt-0.5 flex-shrink-0',
                        error.severity === 'error'
                          ? 'text-red-600'
                          : error.severity === 'warning'
                            ? 'text-amber-600'
                            : 'text-blue-600',
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="mb-0.5 font-medium">
                        {error.field}
                        {nodeLabel && <span className="ml-1 text-gray-500">({nodeLabel})</span>}
                      </div>
                      <div
                        className={cn(
                          'text-xs',
                          error.severity === 'error'
                            ? 'text-red-800'
                            : error.severity === 'warning'
                              ? 'text-amber-800'
                              : 'text-blue-800',
                        )}
                      >
                        {error.message}
                      </div>
                      {isClickable && (
                        <div className="mt-1 text-[9px] italic text-gray-400">
                          {t('workspace.clickToNavigate')}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-gray-100 bg-gray-50 px-3 py-1.5 font-mono text-[9px] text-gray-400">
        <span>
          {hasErrors
            ? t('workspace.cannotDeploy')
            : hasWarnings
              ? t('workspace.deployWithWarnings')
              : t('workspace.readyToDeploy')}
        </span>
        <span className="flex items-center gap-1">
          <div
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              hasErrors ? 'bg-red-500' : hasWarnings ? 'bg-amber-500' : 'bg-green-500',
            )}
          />
          {hasErrors
            ? t('workspace.errors')
            : hasWarnings
              ? t('workspace.warnings')
              : t('workspace.valid')}
        </span>
      </div>
    </div>
  )
}

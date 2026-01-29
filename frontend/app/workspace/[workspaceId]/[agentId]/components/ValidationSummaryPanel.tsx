'use client'

import { X, AlertCircle, CheckCircle2, ArrowRight, FileX, GitBranch, Network } from 'lucide-react'
import React, { useMemo } from 'react'
import { Node, Edge } from 'reactflow'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'


import { validateDeepAgentsStructure } from '../services/deepAgentsValidator'
import { validateGraphConsistency, hasCriticalErrors } from '../services/edgeValidator'
import { validateNodeConfig } from '../services/nodeConfigValidator'
import { ValidationError } from '../types/graph'

interface ValidationSummaryPanelProps {
  nodes: Node[]
  edges: Edge[]
  onClose: () => void
  onSelectNode?: (nodeId: string) => void
  onSelectEdge?: (edgeId: string) => void
}

/**
 * ValidationSummaryPanel - Display all validation errors in the graph
 * 
 * Categories:
 * - Node configuration errors
 * - Edge configuration errors
 * - Graph structure errors
 */
export const ValidationSummaryPanel: React.FC<ValidationSummaryPanelProps> = ({
  nodes,
  edges,
  onClose,
  onSelectNode,
  onSelectEdge,
}) => {
  const { t } = useTranslation()

  // Helper to translate category names
  const translateCategory = (category: string): string => {
    switch (category) {
      case 'Graph Structure':
        return t('workspace.graphStructure')
      case 'Node Configuration':
        return t('workspace.nodeConfiguration')
      case 'Edge Configuration':
        return t('workspace.edgeConfiguration')
      case 'DeepAgents Structure':
        return t('workspace.deepAgentsStructure')
      default:
        return category
    }
  }

  // Collect all validation errors with enhanced categorization
  const allErrors = useMemo(() => {
    const errors: Array<ValidationError & { nodeId?: string; edgeId?: string; category: string; canAutoFix?: boolean }> = []

    // 1. Graph structure errors (from edgeValidator)
    const graphErrors = validateGraphConsistency(nodes, edges)
    graphErrors.forEach((error) => {
      // Try to extract node/edge ID from field path
      const nodeMatch = error.field.match(/node\.([^\.]+)/)
      const edgeMatch = error.field.match(/edge\.([^\.]+)/)

      errors.push({
        ...error,
        category: 'Graph Structure',
        nodeId: nodeMatch ? nodeMatch[1] : undefined,
        edgeId: edgeMatch ? edgeMatch[1] : undefined,
        canAutoFix: error.field.includes('route_key') || error.field.includes('source_handle_id'),
      })
    })

    // 2. Node configuration errors (from unified validator)
    nodes.forEach((node) => {
      const nodeType = (node.data as { type?: string })?.type || ''
      const config = (node.data as { config?: Record<string, unknown> })?.config || {}

      // Skip validation for unknown node types
      if (!nodeType || nodeType === 'unknown') {
        return
      }

      const nodeErrors = validateNodeConfig(nodeType, config)

      nodeErrors.forEach((error) => {
        errors.push({
          ...error,
          category: 'Node Configuration',
          nodeId: node.id,
          canAutoFix: error.field.includes('routes') && error.message.includes('must have at least one'),
        })
      })
    })

    // 3. DeepAgents structure errors
    const deepAgentsErrors = validateDeepAgentsStructure(nodes, edges)
    deepAgentsErrors.forEach((error) => {
      errors.push({
        ...error,
        category: 'DeepAgents Structure',
        nodeId: error.nodeId,
        edgeId: error.edgeId,
      })
    })

    // 4. Skip individual edge validation (covered by graph structure validation)
    // This avoids duplicate error reporting

    return errors
  }, [nodes, edges])

  // Group errors by category
  const errorsByCategory = useMemo(() => {
    const grouped: Record<string, typeof allErrors> = {}
    allErrors.forEach((error) => {
      if (!grouped[error.category]) {
        grouped[error.category] = []
      }
      grouped[error.category].push(error)
    })
    return grouped
  }, [allErrors])

  const criticalErrors = allErrors.filter((e) => e.severity === 'error')
  const warnings = allErrors.filter((e) => e.severity === 'warning')
  const hasErrors = criticalErrors.length > 0
  const hasWarnings = warnings.length > 0

  const handleErrorClick = (error: typeof allErrors[0]) => {
    if (error.nodeId && onSelectNode) {
      onSelectNode(error.nodeId)
      onClose()
    } else if (error.edgeId && onSelectEdge) {
      onSelectEdge(error.edgeId)
      onClose()
    }
  }

  return (
    <div className="absolute top-4 right-4 w-[360px] bg-white border border-gray-200 rounded-xl shadow-xl flex flex-col overflow-hidden animate-in slide-in-from-right-10 fade-in duration-300 z-50 max-h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between bg-white shrink-0">
        <div className="flex items-center gap-2.5 text-gray-900 overflow-hidden">
          <div className={cn(
            "p-1 rounded-md border border-gray-100 shadow-sm shrink-0",
            hasErrors ? "bg-red-50 text-red-600" : hasWarnings ? "bg-amber-50 text-amber-600" : "bg-green-50 text-green-600"
          )}>
            {hasErrors ? <AlertCircle size={12} /> : hasWarnings ? <AlertCircle size={12} /> : <CheckCircle2 size={12} />}
          </div>
          <div className="flex flex-col min-w-0">
            <h3 className="font-bold text-sm leading-tight truncate">{t('workspace.validationSummary')}</h3>
            <span className="text-[9px] text-gray-400 uppercase tracking-widest font-bold">
              {allErrors.length} {allErrors.length !== 1 ? t('workspace.issues') : t('workspace.issue')}
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-6 w-6 text-gray-300 hover:text-gray-600 hover:bg-gray-100 shrink-0"
        >
          <X size={14} />
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-3">
        {/* Summary Stats */}
        <div className="grid grid-cols-3 gap-1">
          <div className={cn(
            "px-1.5 py-1 rounded-md border text-center",
            hasErrors ? "bg-red-50 border-red-200" : "bg-gray-50 border-gray-200"
          )}>
            <div className="text-sm font-bold text-red-600 leading-tight">{criticalErrors.length}</div>
            <div className="text-[9px] text-gray-600 uppercase mt-0.5 leading-tight">{t('workspace.errors')}</div>
          </div>
          <div className={cn(
            "px-1.5 py-1 rounded-md border text-center",
            hasWarnings ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-200"
          )}>
            <div className="text-sm font-bold text-amber-600 leading-tight">{warnings.length}</div>
            <div className="text-[9px] text-gray-600 uppercase mt-0.5 leading-tight">{t('workspace.warnings')}</div>
          </div>
          <div className={cn(
            "px-1.5 py-1 rounded-md border text-center",
            allErrors.length === 0 ? "bg-green-50 border-green-200" : "bg-gray-50 border-gray-200"
          )}>
            <div className="text-sm font-bold text-green-600 leading-tight">{nodes.length}</div>
            <div className="text-[9px] text-gray-600 uppercase mt-0.5 leading-tight">{t('workspace.nodes')}</div>
          </div>
        </div>

        {/* Success State */}
        {allErrors.length === 0 && (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <CheckCircle2 size={36} className="text-green-500 mb-2" />
            <h4 className="font-semibold text-sm text-gray-900 mb-1">{t('workspace.allValidationsPassed')}</h4>
            <p className="text-xs text-gray-500">{t('workspace.graphReadyToDeploy')}</p>
          </div>
        )}

        {/* Errors by Category */}
        {Object.entries(errorsByCategory).map(([category, categoryErrors]) => (
          <div key={category} className="space-y-1.5">
            <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
              {category === 'Graph Structure' && <FileX size={11} />}
              {category === 'Node Configuration' && <GitBranch size={11} />}
              {category === 'Edge Configuration' && <ArrowRight size={11} />}
              {category === 'DeepAgents Structure' && <Network size={11} />}
              {translateCategory(category)} ({categoryErrors.length})
            </Label>
            <div className="space-y-1">
              {categoryErrors.map((error, idx) => {
                const node = error.nodeId ? nodes.find((n) => n.id === error.nodeId) : null
                const edge = error.edgeId ? edges.find((e) => e.id === error.edgeId) : null
                const nodeLabel = node ? (node.data as { label?: string })?.label || node.id : null
                const isClickable = (error.nodeId && onSelectNode) || (error.edgeId && onSelectEdge)

                return (
                  <div
                    key={idx}
                    onClick={() => isClickable && handleErrorClick(error)}
                    className={cn(
                      "flex items-start gap-1.5 p-2 rounded-lg border text-xs transition-colors",
                      error.severity === 'error'
                        ? "bg-red-50 border-red-200"
                        : error.severity === 'warning'
                        ? "bg-amber-50 border-amber-200"
                        : "bg-blue-50 border-blue-200",
                      isClickable && "cursor-pointer hover:shadow-sm"
                    )}
                  >
                    <AlertCircle
                      size={12}
                      className={cn(
                        "mt-0.5 flex-shrink-0",
                        error.severity === 'error' ? "text-red-600" : error.severity === 'warning' ? "text-amber-600" : "text-blue-600"
                      )}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium mb-0.5">
                        {error.field}
                        {nodeLabel && (
                          <span className="text-gray-500 ml-1">({nodeLabel})</span>
                        )}
                      </div>
                      <div className={cn(
                        "text-xs",
                        error.severity === 'error' ? "text-red-800" : error.severity === 'warning' ? "text-amber-800" : "text-blue-800"
                      )}>
                        {error.message}
                      </div>
                      {isClickable && (
                        <div className="text-[9px] text-gray-400 mt-1 italic">
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
      <div className="px-3 py-1.5 border-t border-gray-100 bg-gray-50 flex items-center justify-between text-[9px] text-gray-400 font-mono">
        <span>
          {hasErrors ? t('workspace.cannotDeploy') : hasWarnings ? t('workspace.deployWithWarnings') : t('workspace.readyToDeploy')}
        </span>
        <span className="flex items-center gap-1">
          <div className={cn(
            "w-1.5 h-1.5 rounded-full",
            hasErrors ? "bg-red-500" : hasWarnings ? "bg-amber-500" : "bg-green-500"
          )} />
          {hasErrors ? t('workspace.errors') : hasWarnings ? t('workspace.warnings') : t('workspace.valid')}
        </span>
      </div>
    </div>
  )
}


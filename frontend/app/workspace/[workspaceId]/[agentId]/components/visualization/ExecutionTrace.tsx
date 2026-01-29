'use client'

import { ChevronDown, ChevronRight, ArrowRight } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

import { StateViewer, type GraphState } from './StateViewer'

export interface TraceStep {
  nodeId: string
  nodeType: string
  timestamp: number
  command: {
    update: Record<string, any>
    goto?: string
    reason?: string
  }
  stateSnapshot: GraphState
  routeDecision?: {
    result: boolean | string
    reason: string
    goto: string
  }
}

interface ExecutionTraceProps {
  trace: TraceStep[]
  maxSteps?: number
}

/**
 * 执行轨迹可视化组件
 * 显示完整的执行路径和状态变化
 */
export const ExecutionTrace: React.FC<ExecutionTraceProps> = ({
  trace,
  maxSteps = 50
}) => {
  const { t } = useTranslation()
  const [expandedSteps, setExpandedSteps] = React.useState<Set<number>>(new Set())
  const [showAll, setShowAll] = React.useState(false)

  const toggleStep = (index: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const displayTrace = showAll ? trace : trace.slice(-maxSteps)
  const hasMore = trace.length > maxSteps

  return (
    <div className="execution-trace border border-gray-200 rounded-lg bg-white">
      {/* Header */}
      <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">{t('trace.title', { defaultValue: '执行轨迹' })}</h3>
        <div className="text-xs text-gray-500">
          {t('trace.totalSteps', {
            defaultValue: '共 {{count}} 步',
            count: trace.length
          }).replace('{{count}}', trace.length.toString())}
          {hasMore && !showAll && ` (${t('trace.showingRecent', {
            defaultValue: '显示最近 {{maxSteps}} 步',
            maxSteps: maxSteps
          }).replace('{{maxSteps}}', maxSteps.toString())})`}
        </div>
      </div>

      {/* Trace List */}
      <div className="divide-y divide-gray-200 max-h-96 overflow-y-auto">
        {displayTrace.map((step, index) => {
          const actualIndex = showAll ? index : trace.length - maxSteps + index
          const isExpanded = expandedSteps.has(actualIndex)
          
          return (
            <div key={actualIndex} className="trace-step">
              {/* Step Header */}
              <button
                onClick={() => toggleStep(actualIndex)}
                className="w-full px-3 py-2 flex items-center justify-between hover:bg-gray-50 transition-colors text-left"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <span className="text-xs font-mono text-gray-400 w-8 text-right">
                    #{actualIndex + 1}
                  </span>
                  <span className="text-xs font-semibold text-gray-700 truncate">
                    {step.nodeId}
                  </span>
                  <span className="text-xs text-gray-500 px-1.5 py-0.5 bg-gray-100 rounded">
                    {step.nodeType}
                  </span>
                  {step.command.goto && (
                    <div className="flex items-center gap-1 text-xs text-blue-600 ml-auto">
                      <ArrowRight size={12} />
                      <span className="font-mono">{step.command.goto}</span>
                    </div>
                  )}
                </div>
                {isExpanded ? (
                  <ChevronDown size={14} className="text-gray-400 flex-shrink-0" />
                ) : (
                  <ChevronRight size={14} className="text-gray-400 flex-shrink-0" />
                )}
              </button>

              {/* Step Details */}
              {isExpanded && (
                <div className="px-3 pb-3 space-y-2 bg-gray-50">
                  {/* 路由决策 */}
                  {step.routeDecision && (
                    <div className="text-xs">
                      <span className="text-gray-500">{t('trace.routeDecision', { defaultValue: '路由决策:' })}</span>{' '}
                      <span className="font-medium text-blue-600">
                        {typeof step.routeDecision.result === 'boolean'
                          ? (step.routeDecision.result ? 'True' : 'False')
                          : step.routeDecision.result}
                      </span>
                      {step.routeDecision.reason && (
                        <div className="text-gray-600 mt-1 ml-4">
                          {step.routeDecision.reason}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 状态变化 */}
                  {Object.keys(step.command.update).length > 0 && (
                    <details className="text-xs">
                      <summary className="cursor-pointer text-gray-600 hover:text-gray-800 font-medium">
                        {t('trace.stateChange', { defaultValue: '状态变化' })}
                      </summary>
                      <pre className="mt-1 bg-white p-2 rounded border border-gray-200 overflow-x-auto text-xs">
                        {JSON.stringify(step.command.update, null, 2)}
                      </pre>
                    </details>
                  )}

                  {/* 状态快照 */}
                  <details className="text-xs">
                    <summary className="cursor-pointer text-gray-600 hover:text-gray-800 font-medium">
                      {t('trace.stateSnapshot', { defaultValue: '状态快照' })}
                    </summary>
                    <div className="mt-1">
                      <StateViewer
                        state={step.stateSnapshot}
                        nodeId={step.nodeId}
                        compact={false}
                      />
                    </div>
                  </details>

                  {/* 时间戳 */}
                  <div className="text-xs text-gray-400 pt-1 border-t border-gray-200">
                    {new Date(step.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Show More/Less Button */}
      {hasMore && (
        <div className="px-3 py-2 border-t border-gray-200 bg-gray-50">
          <button
            onClick={() => setShowAll(!showAll)}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            {showAll ? t('trace.showRecent', { defaultValue: '显示最近步骤' }) : t('trace.showAll', { defaultValue: '显示全部步骤' })}
          </button>
        </div>
      )}
    </div>
  )
}

